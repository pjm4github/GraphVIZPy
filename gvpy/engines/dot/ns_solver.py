"""Network simplex solver - NumPy-accelerated.

Standalone implementation of the network simplex algorithm used by
both Phase 1 (rank assignment) and Phase 3 (X-coordinate position
solving) in the dot engine.

C analogue: lib/dotgen/ns.c (in Graphviz).  Same vectorised hot
loops, same feasible-tree construction, same enter/leave edge
selection.  Internally all node names are mapped to integer indices
0..N-1 and edge data is stored in four parallel NumPy int64 arrays
(_e_tail, _e_head, _e_minlen, _e_weight).  Ranks, DFS ranges
(_low / _lim), cut values, and tree membership are also NumPy
arrays, enabling vectorised hot loops in _compute_all_cutvalues,
_enter_edge, _feasible_tree, and _update.

Used by:
  - gvpy.engines.dot.rank      -- network_simplex_rank,
                                  cluster_aware_rank
  - gvpy.engines.dot.position  -- ns_x_position,
                                  bottomup_ns_x_position

A re-export _NetworkSimplex is kept in dot_layout.py so any
existing imports of
    from gvpy.engines.dot.dot_layout import _NetworkSimplex
continue to work.  New code should import from this module
directly.
"""
from __future__ import annotations

from collections import deque

import numpy as np


class _NetworkSimplex:
    """Network simplex for ranking / positioning — NumPy-accelerated.

    Internally all node names are mapped to integer indices ``0 .. N-1``
    and edge data is stored in four parallel NumPy int32 arrays
    (``_e_tail``, ``_e_head``, ``_e_minlen``, ``_e_weight``).  Ranks,
    DFS ranges (``_low`` / ``_lim``), cut values, and tree membership
    are also NumPy arrays, enabling vectorised hot-loops in
    ``_compute_all_cutvalues``, ``_enter_edge``, ``_feasible_tree``,
    and ``_update``.
    """

    SEARCH_LIMIT = 30

    # ── Construction ─────────────────────────────

    def __init__(self, node_names: list[str],
                 edges: list[tuple[str, str, int, int]]):
        """*edges*: list of ``(tail, head, minlen, weight)``."""
        self.node_names = list(node_names)
        N = len(self.node_names)

        # Name ↔ index maps
        self._n2i: dict[str, int] = {n: i for i, n in enumerate(self.node_names)}
        self._N = N

        # Store original edge tuples for _connect_components / callers
        self._edges_raw: list[tuple[str, str, int, int]] = list(edges)

        # Build NumPy edge arrays
        self._rebuild_edge_arrays()

        # Rank array (filled by _init_rank / caller)
        self.rank = np.zeros(N, dtype=np.int64)

        # Tree membership (bool per edge)
        self._in_tree: np.ndarray = np.zeros(len(edges), dtype=np.bool_)
        self._tree_list: np.ndarray = np.empty(0, dtype=np.intp)  # sorted edge indices

        # Cut values (one per edge, only meaningful for tree edges)
        self._cut: np.ndarray = np.zeros(len(edges), dtype=np.int64)

        # DFS range arrays
        self._low = np.zeros(N, dtype=np.int64)
        self._lim = np.zeros(N, dtype=np.int64)
        self._par_edge = np.full(N, -1, dtype=np.intp)  # parent edge index

        self._si = 0  # search start for _leave_edge

        # Precompute adjacency (node index → list of edge indices)
        self._out: list[list[int]] = [[] for _ in range(N)]
        self._inc: list[list[int]] = [[] for _ in range(N)]
        for i in range(len(self._edges_raw)):
            t_str, h_str = self._edges_raw[i][0], self._edges_raw[i][1]
            ti, hi = self._n2i[t_str], self._n2i[h_str]
            self._out[ti].append(i)
            self._inc[hi].append(i)

        # Weighted-edge mask (precomputed after edges finalised)
        self._we_mask: np.ndarray | None = None

    def _rebuild_edge_arrays(self):
        """(Re)build the four parallel NumPy edge arrays from _edges_raw."""
        E = len(self._edges_raw)
        self._e_tail = np.empty(E, dtype=np.intp)
        self._e_head = np.empty(E, dtype=np.intp)
        self._e_minlen = np.empty(E, dtype=np.int64)
        self._e_weight = np.empty(E, dtype=np.int64)
        n2i = self._n2i
        for i, (t, h, ml, w) in enumerate(self._edges_raw):
            self._e_tail[i] = n2i[t]
            self._e_head[i] = n2i[h]
            self._e_minlen[i] = ml
            self._e_weight[i] = w

    @property
    def edges(self):          # back-compat for callers reading tuples
        return self._edges_raw

    # ── Vectorised helpers ───────────────────────

    def _slack_all(self) -> np.ndarray:
        """Slack of every edge as a 1-D int64 array."""
        return self.rank[self._e_head] - self.rank[self._e_tail] - self._e_minlen

    def _slack(self, ei: int) -> int:
        return int(self.rank[self._e_head[ei]]
                   - self.rank[self._e_tail[ei]]
                   - self._e_minlen[ei])

    # ── Initial feasible ranking ─────────────────

    def _init_rank(self):
        """Compute initial feasible ranks using iterative relaxation.

        Uses Bellman-Ford style relaxation: repeatedly scan all edges
        and update head ranks until no more changes.  This handles
        non-DAG constraint topologies where simple BFS misses backward
        constraints (e.g. weight=0 separation edges between nodes that
        are also connected via edge-pair or containment constraints).
        """
        N = self._N
        E = len(self._edges_raw)
        self.rank[:] = 0

        # Bellman-Ford: relax all edges up to N times
        tails = self._e_tail[:E]
        heads = self._e_head[:E]
        minlens = self._e_minlen[:E]
        for _ in range(N):
            needed = self.rank[tails] + minlens
            violations = self.rank[heads] < needed
            if not violations.any():
                break
            np.maximum.at(self.rank, heads[violations],
                          needed[violations])

    # ── Spanning tree construction ───────────────

    def _feasible_tree(self):
        E = len(self._edges_raw)
        N = self._N
        self._in_tree[:E] = False
        in_tree_node = np.zeros(N, dtype=np.bool_)

        if N == 0:
            return
        in_tree_node[0] = True

        slacks = self._slack_all()

        # Greedy: add tight edges (slack == 0) via repeated scan
        changed = True
        while changed:
            changed = False
            tight = (slacks == 0) & ~self._in_tree[:E]
            for ei in np.where(tight)[0]:
                ti, hi = int(self._e_tail[ei]), int(self._e_head[ei])
                if in_tree_node[ti] and not in_tree_node[hi]:
                    self._in_tree[ei] = True
                    in_tree_node[hi] = True
                    changed = True
                elif in_tree_node[hi] and not in_tree_node[ti]:
                    self._in_tree[ei] = True
                    in_tree_node[ti] = True
                    changed = True

        # Add minimum-slack edges for remaining nodes
        n_in_tree = int(in_tree_node.sum())
        while n_in_tree < N:
            not_tree_edges = ~self._in_tree[:E]
            t_in = in_tree_node[self._e_tail[:E]]
            h_in = in_tree_node[self._e_head[:E]]
            crossing = (t_in != h_in) & not_tree_edges
            if not crossing.any():
                # Disconnected node — just add it
                for i in range(N):
                    if not in_tree_node[i]:
                        in_tree_node[i] = True
                        n_in_tree += 1
                        break
                continue

            abs_slack = np.abs(slacks)
            abs_slack[~crossing] = np.iinfo(np.int64).max
            best_ei = int(np.argmin(abs_slack))

            delta = int(slacks[best_ei])
            ti = int(self._e_tail[best_ei])
            if in_tree_node[ti]:
                # Shift ALL tree nodes UP
                self.rank[in_tree_node] += delta
            else:
                # Shift ALL tree nodes DOWN
                self.rank[in_tree_node] -= delta
            slacks = self._slack_all()  # refresh after rank shift

            self._in_tree[best_ei] = True
            in_tree_node[self._e_tail[best_ei]] = True
            in_tree_node[self._e_head[best_ei]] = True
            n_in_tree = int(in_tree_node.sum())

            # Try adding more tight edges
            changed = True
            while changed:
                changed = False
                tight = (slacks == 0) & ~self._in_tree[:E]
                for ei in np.where(tight)[0]:
                    ti2, hi2 = int(self._e_tail[ei]), int(self._e_head[ei])
                    if in_tree_node[ti2] and not in_tree_node[hi2]:
                        self._in_tree[ei] = True
                        in_tree_node[hi2] = True
                        n_in_tree += 1
                        changed = True
                    elif in_tree_node[hi2] and not in_tree_node[ti2]:
                        self._in_tree[ei] = True
                        in_tree_node[ti2] = True
                        n_in_tree += 1
                        changed = True

    # ── DFS range for subtree queries ────────────

    def _dfs_range(self):
        N = self._N
        if N == 0:
            return
        # Build tree adjacency from edge arrays
        tree_idx = np.where(self._in_tree[:len(self._edges_raw)])[0]
        adj: list[list[tuple[int, int]]] = [[] for _ in range(N)]
        for ei in tree_idx:
            ti, hi = int(self._e_tail[ei]), int(self._e_head[ei])
            adj[ti].append((int(ei), hi))
            adj[hi].append((int(ei), ti))

        self._par_edge[:] = -1
        self._low[:] = 0
        self._lim[:] = 0
        counter = 0

        # Iterative DFS from node 0
        stack: list[tuple[int, int, bool]] = [(0, -1, False)]
        visited = np.zeros(N, dtype=np.bool_)
        while stack:
            node, par_ei, returning = stack[-1]
            if not returning:
                self._low[node] = counter
                counter += 1
                visited[node] = True
                stack[-1] = (node, par_ei, True)
                for ei, nbr in adj[node]:
                    if not visited[nbr]:
                        self._par_edge[nbr] = ei
                        stack.append((nbr, ei, False))
            else:
                self._lim[node] = counter
                counter += 1
                stack.pop()

    def _subtree_mask(self, sub_root: int) -> np.ndarray:
        """Bool mask: which nodes are in the subtree rooted at *sub_root*."""
        lo, li = int(self._low[sub_root]), int(self._lim[sub_root])
        return (self._low >= lo) & (self._low <= li)

    # ── Cut values (vectorised) ──────────────────

    def _init_cutvalues(self):
        self._dfs_range()
        E = len(self._edges_raw)
        self._cut = np.zeros(E, dtype=np.int64)
        # Weighted-edge mask (skip w==0 edges for cut-value sums)
        self._we_mask = self._e_weight[:E] != 0
        self._tree_list = np.where(self._in_tree[:E])[0]
        self._compute_all_cutvalues()

    def _compute_all_cutvalues(self):
        """Vectorised cut-value computation for ALL tree edges at once."""
        E = len(self._edges_raw)
        we = self._we_mask
        if we is None or not we.any():
            return

        # Weighted edge data (only non-zero weight)
        we_tails = self._e_tail[:E][we]
        we_heads = self._e_head[:E][we]
        we_weights = self._e_weight[:E][we]
        we_low_t = self._low[we_tails]
        we_low_h = self._low[we_heads]

        for tree_ei in self._tree_list:
            ti = int(self._e_tail[tree_ei])
            hi = int(self._e_head[tree_ei])
            if self._lim[ti] < self._lim[hi]:
                sub_low = int(self._low[ti])
                sub_lim = int(self._lim[ti])
                direction = 1
            else:
                sub_low = int(self._low[hi])
                sub_lim = int(self._lim[hi])
                direction = -1

            t_in = (we_low_t >= sub_low) & (we_low_t <= sub_lim)
            h_in = (we_low_h >= sub_low) & (we_low_h <= sub_lim)
            crossing = t_in != h_in
            if not crossing.any():
                self._cut[tree_ei] = 0
                continue
            signs = np.where(t_in[crossing], direction, -direction)
            self._cut[tree_ei] = int(np.dot(signs, we_weights[crossing]))

    # ── Pivot operations ─────────────────────────

    def _leave_edge(self) -> int | None:
        tl = self._tree_list
        n = len(tl)
        if n == 0:
            return None
        # Gather cut values for tree edges
        cvs = self._cut[tl]
        neg = cvs < 0
        if not neg.any():
            return None
        # Respect SEARCH_LIMIT: pick the first (up to SEARCH_LIMIT)
        # negative cut value starting from _si
        start = self._si % n
        order = np.roll(np.arange(n), -start)
        neg_positions = order[neg[order]]
        if len(neg_positions) == 0:
            return None
        # Pick the most negative among the first SEARCH_LIMIT candidates
        candidates = neg_positions[:self.SEARCH_LIMIT]
        best_local = candidates[np.argmin(cvs[candidates])]
        self._si = (int(best_local) + 1) % n
        return int(tl[best_local])

    def _enter_edge(self, leaving_ei: int) -> int | None:
        ti = int(self._e_tail[leaving_ei])
        hi = int(self._e_head[leaving_ei])
        sub_root = ti if self._lim[ti] < self._lim[hi] else hi
        sub_low = int(self._low[sub_root])
        sub_lim = int(self._lim[sub_root])

        E = len(self._edges_raw)
        t_low = self._low[self._e_tail[:E]]
        h_low = self._low[self._e_head[:E]]
        t_in = (t_low >= sub_low) & (t_low <= sub_lim)
        h_in = (h_low >= sub_low) & (h_low <= sub_lim)
        crossing = (t_in != h_in) & ~self._in_tree[:E]
        if not crossing.any():
            return None
        slacks = self._slack_all()
        feasible = crossing & (slacks >= 0)
        if not feasible.any():
            return None
        candidates = np.where(feasible)[0]
        return int(candidates[np.argmin(slacks[candidates])])

    def _update(self, leaving_ei: int, entering_ei: int):
        delta = self._slack(entering_ei)
        if delta != 0:
            ti = int(self._e_tail[leaving_ei])
            hi = int(self._e_head[leaving_ei])
            sub_root = ti if self._lim[ti] < self._lim[hi] else hi
            mask = self._subtree_mask(sub_root)

            # Determine shift direction from entering edge
            ent_t = int(self._e_tail[entering_ei])
            shift = delta if mask[ent_t] else -delta
            self.rank[mask] += shift

        # Exchange tree edges
        self._in_tree[leaving_ei] = False
        self._in_tree[entering_ei] = True

        # Recompute DFS ranges and cut values
        self._init_cutvalues()

    # ── Normalize ────────────────────────────────

    def _normalize(self):
        if self._N > 0:
            self.rank -= self.rank.min()

    # ── Main entry point ─────────────────────────

    def solve(self, max_iter: int = 200,
              initial_ranks: dict[str, int] | None = None) -> dict[str, int]:
        if not self.node_names:
            return {}
        if initial_ranks:
            for n, i in self._n2i.items():
                self.rank[i] = initial_ranks.get(n, 0)
            # Light feasibility fixup (2 passes)
            E = len(self._edges_raw)
            for _pass in range(2):
                needed = self.rank[self._e_tail[:E]] + self._e_minlen[:E]
                violations = self.rank[self._e_head[:E]] < needed
                if violations.any():
                    for ei in np.where(violations)[0]:
                        h = int(self._e_head[ei])
                        self.rank[h] = max(int(self.rank[h]),
                                           int(needed[ei]))
        else:
            self._init_rank()
        if self._N <= 1:
            self._normalize()
            return {n: int(self.rank[i]) for n, i in self._n2i.items()}
        self._connect_components()
        if not self._edges_raw:
            self._normalize()
            return {n: int(self.rank[i]) for n, i in self._n2i.items()}
        self._feasible_tree()
        self._init_cutvalues()
        for _ in range(max_iter):
            leaving = self._leave_edge()
            if leaving is None:
                break
            entering = self._enter_edge(leaving)
            if entering is None:
                break
            self._update(leaving, entering)
        self._normalize()
        return {n: int(self.rank[i]) for n, i in self._n2i.items()}

    def _connect_components(self):
        """Add zero-weight edges between disconnected components."""
        N = self._N
        adj: list[list[int]] = [[] for _ in range(N)]
        seen: list[set[int]] = [set() for _ in range(N)]
        for t, h in zip(self._e_tail, self._e_head):
            ti, hi = int(t), int(h)
            if hi not in seen[ti]:
                seen[ti].add(hi)
                adj[ti].append(hi)
            if ti not in seen[hi]:
                seen[hi].add(ti)
                adj[hi].append(ti)
        visited = np.zeros(N, dtype=np.bool_)
        components: list[list[int]] = []
        for start in range(N):
            if visited[start]:
                continue
            comp: list[int] = []
            queue = deque([start])
            while queue:
                u = queue.popleft()
                if visited[u]:
                    continue
                visited[u] = True
                comp.append(u)
                for v in adj[u]:
                    if not visited[v]:
                        queue.append(v)
            components.append(comp)
        # Link components with dummy edges
        for i in range(1, len(components)):
            t_idx = components[i - 1][0]
            h_idx = components[i][0]
            t_name = self.node_names[t_idx]
            h_name = self.node_names[h_idx]
            self._edges_raw.append((t_name, h_name, 0, 0))
            self._out[t_idx].append(len(self._edges_raw) - 1)
            self._inc[h_idx].append(len(self._edges_raw) - 1)
        # Rebuild NumPy arrays if edges were added
        if len(components) > 1:
            self._rebuild_edge_arrays()
            E = len(self._edges_raw)
            self._in_tree = np.zeros(E, dtype=np.bool_)
            self._cut = np.zeros(E, dtype=np.int64)

