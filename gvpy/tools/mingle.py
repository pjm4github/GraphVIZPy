"""
Mingle edge bundling — agglomerative ink-based edge bundling.

Port of Graphviz ``lib/mingle/``.  This is a post-processor, not a
layout engine.  It takes a layout result dict (with positioned nodes
and straight-line edges) and computes bundled edge paths with shared
intermediate control points.

Algorithm (agglomerative ink bundling):

1. Compute edge compatibility scores between all edge pairs
2. Greedy matching: pair compatible edges that save ink when bundled
3. Compute meeting points for each bundle (ternary search)
4. Insert meeting points as control points in edge paths
5. Recursively coarsen until no more ink savings

Edge compatibility (Holten-van Wijk, 2009):
  - Angle compatibility: |cos(angle between edge directions)|
  - Scale compatibility: similarity of edge lengths
  - Position compatibility: proximity of edge midpoints
  - Combined: product of all three

Ink savings:
  The "ink" of a set of edges is the total path length.  Bundling
  reduces ink by routing edges through shared meeting points.

Command-line usage::

    python gvcli.py -Kneato input.gv -Tsvg --bundle
    python gvtools.py mingle input_with_pos.gv

API usage::

    from gvpy.tools.mingle import MingleBundler
    bundled = MingleBundler.bundle_result(layout_result)
    # or
    bundler = MingleBundler(graph)
    bundler.bundle()  # modifies edge positions in-place
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from gvpy.core.graph import Graph


# ── Data structures ─────────────────────────────

@dataclass
class _Edge:
    """Internal edge representation for bundling."""
    idx: int
    x1: float
    y1: float
    x2: float
    y2: float
    weight: float = 1.0
    points: list[tuple[float, float]] = field(default_factory=list)
    # Direction vector (normalized)
    dx: float = 0.0
    dy: float = 0.0
    length: float = 0.0
    midx: float = 0.0
    midy: float = 0.0

    def __post_init__(self):
        self.dx = self.x2 - self.x1
        self.dy = self.y2 - self.y1
        self.length = math.sqrt(self.dx * self.dx + self.dy * self.dy)
        if self.length > 0:
            self.dx /= self.length
            self.dy /= self.length
        self.midx = (self.x1 + self.x2) / 2
        self.midy = (self.y1 + self.y2) / 2
        self.points = [(self.x1, self.y1), (self.x2, self.y2)]


# ── Compatibility scoring ────────────────────────

def _angle_compat(e1: _Edge, e2: _Edge) -> float:
    """Angle compatibility: |cos(angle between directions)|."""
    dot = e1.dx * e2.dx + e1.dy * e2.dy
    return abs(dot)


def _scale_compat(e1: _Edge, e2: _Edge) -> float:
    """Scale compatibility: similarity of edge lengths."""
    avg = (e1.length + e2.length) / 2
    if avg < 0.01:
        return 0.0
    mx = max(e1.length, e2.length)
    mn = min(e1.length, e2.length)
    if mn < 0.01:
        return 0.0
    return 2.0 / (mx / avg + avg / mn)


def _position_compat(e1: _Edge, e2: _Edge) -> float:
    """Position compatibility: proximity of midpoints."""
    avg = (e1.length + e2.length) / 2
    if avg < 0.01:
        return 0.0
    dx = e1.midx - e2.midx
    dy = e1.midy - e2.midy
    mid_dist = math.sqrt(dx * dx + dy * dy)
    return avg / (avg + mid_dist)


def _edge_compatibility(e1: _Edge, e2: _Edge) -> float:
    """Combined edge compatibility score (Holten-van Wijk).

    Returns value in [0, 1].  Higher = more compatible.
    """
    a = _angle_compat(e1, e2)
    if a < 0.1:
        return 0.0
    s = _scale_compat(e1, e2)
    if s < 0.1:
        return 0.0
    p = _position_compat(e1, e2)
    return a * s * p


# ── Ink computation ──────────────────────────────

def _ink_single(e: _Edge) -> float:
    """Ink of a single edge (just its length)."""
    return e.length * e.weight


def _ink_bundled(e1: _Edge, e2: _Edge) -> tuple[float, tuple[float, float], tuple[float, float]]:
    """Compute ink of bundling two edges, and the optimal meeting points.

    The meeting points are placed at a fraction along each edge's
    direction, then averaged.  A ternary search finds the optimal
    fraction that minimizes total ink.

    Returns (ink, meet_point_1, meet_point_2).
    """
    w1, w2 = e1.weight, e2.weight
    total_w = w1 + w2

    def _compute_ink(frac):
        """Compute ink for meeting points at fraction `frac` along edges."""
        # Meeting point 1: fraction along from source ends
        m1x = (e1.x1 + frac * (e1.x2 - e1.x1)) * w1 / total_w + \
              (e2.x1 + frac * (e2.x2 - e2.x1)) * w2 / total_w
        m1y = (e1.y1 + frac * (e1.y2 - e1.y1)) * w1 / total_w + \
              (e2.y1 + frac * (e2.y2 - e2.y1)) * w2 / total_w
        # Meeting point 2: fraction from target ends
        m2x = (e1.x2 - frac * (e1.x2 - e1.x1)) * w1 / total_w + \
              (e2.x2 - frac * (e2.x2 - e2.x1)) * w2 / total_w
        m2y = (e1.y2 - frac * (e1.y2 - e1.y1)) * w1 / total_w + \
              (e2.y2 - frac * (e2.y2 - e2.y1)) * w2 / total_w

        # Shared segment (counted ONCE, not per-edge)
        shared = math.sqrt((m2x - m1x) ** 2 + (m2y - m1y) ** 2)
        # Unshared segments (each edge pays its own spur cost)
        ink = shared  # shared path counted once
        for e in (e1, e2):
            d_src = math.sqrt((m1x - e.x1) ** 2 + (m1y - e.y1) ** 2)
            d_tgt = math.sqrt((e.x2 - m2x) ** 2 + (e.y2 - m2y) ** 2)
            ink += (d_src + d_tgt) * e.weight
        return ink, (m1x, m1y), (m2x, m2y)

    # Ternary search for optimal fraction in [0.01, 0.49]
    lo, hi = 0.01, 0.49
    for _ in range(20):
        m1 = lo + (hi - lo) / 3
        m2 = hi - (hi - lo) / 3
        ink1, _, _ = _compute_ink(m1)
        ink2, _, _ = _compute_ink(m2)
        if ink1 < ink2:
            hi = m2
        else:
            lo = m1

    best_frac = (lo + hi) / 2
    return _compute_ink(best_frac)


# ── Agglomerative bundling ───────────────────────

def _agglomerative_bundle(edges: list[_Edge],
                          compat_threshold: float = 0.5,
                          max_levels: int = 5) -> list[_Edge]:
    """Agglomerative ink-based edge bundling.

    Greedily pairs compatible edges that reduce total ink,
    then recurses on the coarsened edge set.
    """
    if len(edges) <= 1:
        return edges

    for level in range(max_levels):
        # Compute compatibility between all pairs
        N = len(edges)
        if N <= 1:
            break

        # Find best match for each edge
        matched = [False] * N
        pairs: list[tuple[int, int]] = []

        for i in range(N):
            if matched[i]:
                continue
            best_j = -1
            best_saving = 0.0

            for j in range(i + 1, N):
                if matched[j]:
                    continue
                compat = _edge_compatibility(edges[i], edges[j])
                if compat < compat_threshold:
                    continue

                # Check if bundling saves ink
                ink_separate = _ink_single(edges[i]) + _ink_single(edges[j])
                ink_bundle, _, _ = _ink_bundled(edges[i], edges[j])
                saving = ink_separate - ink_bundle

                if saving > best_saving:
                    best_saving = saving
                    best_j = j

            if best_j >= 0:
                matched[i] = True
                matched[best_j] = True
                pairs.append((i, best_j))

        if not pairs:
            break  # No more savings possible

        # Merge paired edges
        new_edges: list[_Edge] = []
        merged = set()
        for i, j in pairs:
            merged.add(i)
            merged.add(j)
            e1, e2 = edges[i], edges[j]
            _, meet1, meet2 = _ink_bundled(e1, e2)

            # Update edge points to go through meeting points
            e1.points = [(e1.x1, e1.y1), meet1, meet2, (e1.x2, e1.y2)]
            e2.points = [(e2.x1, e2.y1), meet1, meet2, (e2.x2, e2.y2)]

            # Create merged edge for next level
            w = e1.weight + e2.weight
            merged_edge = _Edge(
                idx=e1.idx,
                x1=meet1[0], y1=meet1[1],
                x2=meet2[0], y2=meet2[1],
                weight=w,
            )
            new_edges.append(merged_edge)

        # Keep unmatched edges
        for i in range(N):
            if i not in merged:
                new_edges.append(edges[i])

        edges = new_edges

    return edges


# ── Public API ───────────────────────────────────


class MingleBundler:
    """Edge bundling post-processor.

    NOT a layout engine — operates on pre-positioned edges.
    """

    def __init__(self, graph: Graph):
        self.graph = graph
        self.compat_threshold = 0.5
        self.max_levels = 5

    def layout(self) -> dict:
        """Not a layout engine — raises NotImplementedError.

        Use ``bundle()`` or ``bundle_result()`` instead.
        """
        raise NotImplementedError(
            "Mingle is an edge bundler, not a layout engine. "
            "Run a layout engine first (e.g. neato, fdp), then apply "
            "MingleBundler.bundle_result(layout_result) to bundle edges."
        )

    def bundle(self) -> None:
        """Bundle edges in the graph in-place.

        Requires that nodes already have ``pos`` attributes
        (i.e., a layout engine has already been run).
        """
        # Extract edge endpoints from graph
        edges: list[_Edge] = []
        edge_map: list[tuple] = []  # maps _Edge idx → graph edge key

        for idx, (key, edge) in enumerate(self.graph.edges.items()):
            t, h = edge.tail, edge.head
            tx = float(t.attributes.get("pos", "0,0").split(",")[0]) * 72
            ty = float(t.attributes.get("pos", "0,0").split(",")[1]) * 72
            hx = float(h.attributes.get("pos", "0,0").split(",")[0]) * 72
            hy = float(h.attributes.get("pos", "0,0").split(",")[1]) * 72

            try:
                w = float(edge.attributes.get("weight", "1"))
            except ValueError:
                w = 1.0

            e = _Edge(idx=idx, x1=tx, y1=ty, x2=hx, y2=hy, weight=w)
            edges.append(e)
            edge_map.append(key)

        if len(edges) < 2:
            return

        # Run bundling
        _agglomerative_bundle(edges, self.compat_threshold, self.max_levels)

        # Write bundled paths back to graph edges
        for e, key in zip(edges, edge_map):
            if len(e.points) > 2:
                edge = self.graph.edges[key]
                parts = []
                for i, (px, py) in enumerate(e.points):
                    if i == 0:
                        parts.append(f"s,{round(px, 2)},{round(py, 2)}")
                    elif i == len(e.points) - 1:
                        parts.append(f"e,{round(px, 2)},{round(py, 2)}")
                    else:
                        parts.append(f"{round(px, 2)},{round(py, 2)}")
                edge.agset("pos", " ".join(parts))

    @staticmethod
    def bundle_result(result: dict,
                      compat_threshold: float = 0.5,
                      max_levels: int = 5) -> dict:
        """Bundle edges in a layout result dict.

        Takes a layout result (from any engine's ``layout()`` method)
        and returns a new result with bundled edge paths.

        Parameters
        ----------
        result : dict
            Layout result with nodes and edges.
        compat_threshold : float
            Minimum compatibility score for bundling (0-1, default 0.5).
        max_levels : int
            Maximum agglomerative levels (default 5).

        Returns
        -------
        dict
            Modified result with bundled edge points.
        """
        edges_data = result.get("edges", [])
        if len(edges_data) < 2:
            return result

        # Build node position lookup
        node_pos: dict[str, tuple[float, float]] = {}
        for n in result.get("nodes", []):
            node_pos[n["name"]] = (n["x"], n["y"])

        # Create internal edges
        internal_edges: list[_Edge] = []
        for i, ed in enumerate(edges_data):
            pts = ed.get("points", [])
            if len(pts) >= 2:
                x1, y1 = pts[0][0], pts[0][1]
                x2, y2 = pts[-1][0], pts[-1][1]
            else:
                t_pos = node_pos.get(ed.get("tail", ""), (0, 0))
                h_pos = node_pos.get(ed.get("head", ""), (0, 0))
                x1, y1 = t_pos
                x2, y2 = h_pos

            e = _Edge(idx=i, x1=x1, y1=y1, x2=x2, y2=y2)
            internal_edges.append(e)

        # Bundle
        _agglomerative_bundle(internal_edges, compat_threshold, max_levels)

        # Write back bundled paths
        result = dict(result)
        result["edges"] = list(result["edges"])
        for e in internal_edges:
            if len(e.points) > 2:
                idx = e.idx
                if idx < len(result["edges"]):
                    edge_entry = dict(result["edges"][idx])
                    edge_entry["points"] = [[round(p[0], 2), round(p[1], 2)]
                                            for p in e.points]
                    edge_entry["spline_type"] = "bezier"
                    result["edges"][idx] = edge_entry

        return result


# ── CLI entry point for gvtools.py ───────────────

USAGE = """\
Usage: mingle <options> <file>
  -a t      - max. turning angle [0-180] (default 40)
  -c i      - compatibility measure; 0: distance, 1: full (default)
  -i iter   - number of outer iterations/subdivisions (default 4)
  -k k      - number of neighbors in nearest neighbor graph of edges (default 10)
  -K k      - the force constant
  -m method - method: 0 (force directed), 1 (agglomerative ink saving, default),
              2 (cluster+ink saving)
  -o fname  - write output to file fname (default: stdout)
  -p t      - balance for avoiding sharp angles;
              the larger t, the more sharp angles are allowed
  -r R      - max. recursion level with agglomerative ink saving (default 100)
  -T fmt    - output format: gv (default) or simple
  -v        - verbose
  -?        - print usage
Requires nodes to have pos attributes (run a layout engine first).
"""


def run(args):
    """CLI entry: python gvtools.py mingle [options] <file>"""
    if args.get("?"):
        print(USAGE)
        return
    from gvpy.grammar.gv_reader import read_gv, read_gv_file
    from gvpy.grammar.gv_writer import write_gv
    import sys

    f = args.get("file")
    if f and f != "-":
        from pathlib import Path
        graph = read_gv_file(Path(f))
    else:
        graph = read_gv(sys.stdin.read())

    # Parse mingle-specific options
    try:
        max_angle = float(args.get("a", "40"))
    except ValueError:
        max_angle = 40.0

    compat_method = int(args.get("c", "1"))  # 0=distance, 1=full
    iterations = int(args.get("i", "4"))
    n_neighbors = int(args.get("k", "10"))
    method = int(args.get("m", "1"))  # 0=FD, 1=agglom, 2=cluster
    max_recursion = int(args.get("r", "100"))

    try:
        angle_balance = float(args.get("p", "0.5"))
    except ValueError:
        angle_balance = 0.5

    try:
        force_K = float(args.get("K", "0"))
    except ValueError:
        force_K = 0.0

    # Configure bundler
    bundler = MingleBundler(graph)
    bundler.compat_threshold = 0.5 if compat_method == 1 else 0.3
    bundler.max_levels = max_recursion

    bundler.bundle()

    if args.get("v"):
        colored = sum(1 for e in graph.edges.values()
                      if "pos" in e.attributes)
        print(f"mingle: processed {len(graph.edges)} edge(s) "
              f"in graph with {len(graph.nodes)} node(s)",
              file=sys.stderr)

    out = write_gv(graph)
    o = args.get("o")
    if o:
        from pathlib import Path as P
        P(o).write_text(out, encoding="utf-8")
    else:
        print(out, end="")
