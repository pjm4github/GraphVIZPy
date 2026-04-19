"""Count edges whose routed polyline crosses a non-member cluster.

Originally built for a channel-routing A/B metric; the standalone
channel router was removed in commit B4 (its cluster-aware pieces are
now part of ``make_regular_edge``'s ``maximal_bbox`` path).  Still used
by ``tools/visual_audit.py`` as the Python-side crossing counter.  Run:

    python tools/count_cluster_crossings.py test_data/aa1332.dot

Exit status is always 0; results printed to stdout.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gvpy.grammar.gv_reader import read_dot_file
from gvpy.engines.layout.dot.dot_layout import DotLayout


def _sample_bezier(pts, samples_per_seg=12, is_bezier=None):
    """Sample a polyline or Bezier control-point list to a dense polyline.

    ``pts`` is either a raw polyline (anchor-only) or the Graphviz Bezier
    format ``[P0, C1, C2, P1, C3, C4, P2, ...]`` where every group of 4
    control points after the first anchor defines one cubic segment.

    *is_bezier* controls the interpretation explicitly — **callers must
    pass it** for ortho / polyline output since the "(len−1) % 3 == 0"
    shape heuristic wrongly treats a 4-point right-angle Z polyline as
    a single cubic segment and returns a curve that wildly deviates
    from the actual right-angle segments.  If unset we fall back to
    the old heuristic for back-compat.
    """
    n = len(pts)
    if n < 2:
        return list(pts)
    if is_bezier is None:
        is_bezier = n >= 4 and (n - 1) % 3 == 0
    if not is_bezier:
        return list(pts)
    out = [pts[0]]
    for base in range(0, n - 1, 3):
        p0, c1, c2, p3 = pts[base:base + 4]
        for k in range(1, samples_per_seg + 1):
            t = k / samples_per_seg
            s = 1 - t
            x = (s*s*s*p0[0] + 3*s*s*t*c1[0]
                 + 3*s*t*t*c2[0] + t*t*t*p3[0])
            y = (s*s*s*p0[1] + 3*s*s*t*c1[1]
                 + 3*s*t*t*c2[1] + t*t*t*p3[1])
            out.append((x, y))
    return out


def _segments_cross_bbox(pts, bb, is_bezier=None):
    x1, y1, x2, y2 = bb
    sampled = _sample_bezier(pts, is_bezier=is_bezier)
    for (ax, ay), (bx, by) in zip(sampled, sampled[1:]):
        smin_x, smax_x = min(ax, bx), max(ax, bx)
        smin_y, smax_y = min(ay, by), max(ay, by)
        if smax_x < x1 or smin_x > x2 or smax_y < y1 or smin_y > y2:
            continue
        return True
    return False


def _cluster_nodes(layout, cl):
    return set(cl.nodes)


def count_crossings(dot_path: str, use_channel: bool = False):
    """Count edges in *dot_path* crossing non-member cluster bboxes.

    The ``use_channel`` keyword is accepted but no longer has any
    effect — the standalone channel router was removed (its cluster
    clipping is in ``make_regular_edge``'s ``maximal_bbox`` now).
    Kept as a keyword for callers that still pass it, e.g.
    ``tools/visual_audit.py``.
    """
    del use_channel  # obsolete; retained for API back-compat
    graph = read_dot_file(dot_path)
    layout = DotLayout(graph)
    layout.layout()

    cluster_nodes = {cl.name: _cluster_nodes(layout, cl)
                     for cl in layout._clusters if cl.bb}

    crossings = []  # (edge_repr, list of cluster names crossed)
    for le in layout.ledges:
        if le.virtual:
            continue
        pts = le.points or []
        if len(pts) < 2:
            continue
        # Interpret the point list using the edge's recorded spline
        # type — ortho output is a right-angle polyline, not a cubic,
        # so forcing bezier interpretation introduces phantom crossings.
        is_bezier = le.route.spline_type == "bezier"
        offenders = []
        for cl in layout._clusters:
            if not cl.bb:
                continue
            cnodes = cluster_nodes[cl.name]
            # Non-member cluster: neither endpoint belongs to it.
            # (Single-endpoint membership is also legitimate — the
            # edge has to exit through that cluster's wall.)
            if le.tail_name in cnodes or le.head_name in cnodes:
                continue
            if _segments_cross_bbox(pts, cl.bb, is_bezier=is_bezier):
                offenders.append(cl.name)
        if offenders:
            crossings.append((f"{le.tail_name}->{le.head_name}", offenders))
    return crossings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dot_path")
    args = ap.parse_args()

    crossings = count_crossings(args.dot_path)
    mode = "channel OFF"  # kept in the log line for output-format compat
    print(f"[{mode}] {args.dot_path}: "
          f"{len(crossings)} edges cross non-member clusters")
    for edge, offs in crossings:
        print(f"  {edge} -> {', '.join(offs)}")


if __name__ == "__main__":
    main()
