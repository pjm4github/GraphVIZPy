"""Position-phase C-vs-Py structural comparison + overlap audit.

Renders 1879.dot through C dot.exe and Py gvcli, extracts every
node and cluster bbox from both SVGs, then:

1. Pairs nodes by name and reports rank-bucket alignment + Y-scale
   ratio (Py_y / C_y).  Expect ratio ~constant if Py just inflates
   for HTML tables — outliers flag layout drift.
2. Detects node–node, cluster–cluster, and node-vs-non-member-
   cluster overlaps in Py's SVG (key acceptance criterion).
3. Reports the SAME overlap categories in C's SVG for comparison
   (C is the reference; if C also overlaps in some category, that
   doesn't count as a Py regression).

Usage:
    python _position_compare.py [c_svg] [py_svg]
"""
from __future__ import annotations
import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "porting_scripts"))


# ─── SVG parsers ──────────────────────────────────────────────

# C SVG: <g id="clust{N}" class="cluster"> ... <title>cluster_X</title> ... <polygon points="...">
_C_CLUST_BLOCK = re.compile(
    r'<g id="clust\d+"[^>]*class="cluster"[^>]*>\s*<title>([^<]+)</title>(.*?)</g>',
    re.DOTALL)
# C nodes: <g id="nodeN" class="node"> <title>name</title> body </g>
# (Note: g[0] may be id="nodeN", body may include nested <g id="a_nodeN">.)
_C_NODE_BLOCK = re.compile(
    r'<g id="node\d+"[^>]*class="node"[^>]*>\s*<title>([^<]+)</title>(.*?)\n</g>',
    re.DOTALL)
# Py: <g id="cluster_X" class="cluster"> ... <rect x=.. y=.. width=.. height=..>
_PY_CLUST_BLOCK = re.compile(
    r'<g id="(cluster_[^"]+)"[^>]*class="cluster"[^>]*>(.*?)</g>',
    re.DOTALL)
# Py: <g id="node_<actual_node_name>" class="node"> ... <rect x=.. y=.. ...>
# IDs include both "node_node_X" and "node_couple_X" forms.
_PY_NODE_BLOCK = re.compile(
    r'<g id="node_([^"]+)"[^>]*class="node"[^>]*>(.*?)</g>',
    re.DOTALL)

_RECT = re.compile(
    r'<rect[^>]*\sx="([\d.eE+-]+)"\s+y="([\d.eE+-]+)"\s+width="([\d.eE+-]+)"\s+height="([\d.eE+-]+)"')
_ELLIPSE = re.compile(
    r'<ellipse[^>]*\scx="([\d.eE+-]+)"\s+cy="([\d.eE+-]+)"\s+rx="([\d.eE+-]+)"\s+ry="([\d.eE+-]+)"')
_POLYGON = re.compile(r'<polygon[^>]*\spoints="([^"]+)"')
_POLY_PTS = re.compile(r'(-?[\d.eE]+),(-?[\d.eE]+)')
# C SVG uses <image> + <text> for label-only nodes (1879.dot's family-tree
# clusters with HTML-table labels render as image/text in C since C has
# no expat/HTML support).  Treat each as its own bbox.
_IMAGE = re.compile(
    r'<image[^>]*\s(?:xlink:href="[^"]*"\s+)?width="([\d.eE+-]+)(?:px)?"\s+height="([\d.eE+-]+)(?:px)?"[^>]*\sx="([\d.eE+-]+)"\s+y="([\d.eE+-]+)"')
# <text x=.. y=.. font-size="..." > content </text>
_TEXT = re.compile(
    r'<text[^>]*\sx="([\d.eE+-]+)"\s+y="([\d.eE+-]+)"[^>]*font-size="([\d.eE+-]+)"[^>]*>([^<]*)</text>')


def _bbox_from_polygon(points_str):
    pts = [(float(m.group(1)), float(m.group(2)))
           for m in _POLY_PTS.finditer(points_str)]
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _bbox_from_body(body):
    """Best-effort bbox: union of <rect>, <ellipse>, <polygon>,
    <image>, <text>."""
    boxes = []
    for m in _RECT.finditer(body):
        x, y, w, h = (float(m.group(i)) for i in range(1, 5))
        boxes.append((x, y, x + w, y + h))
    for m in _ELLIPSE.finditer(body):
        cx, cy, rx, ry = (float(m.group(i)) for i in range(1, 5))
        boxes.append((cx - rx, cy - ry, cx + rx, cy + ry))
    for m in _POLYGON.finditer(body):
        bb = _bbox_from_polygon(m.group(1))
        if bb:
            boxes.append(bb)
    for m in _IMAGE.finditer(body):
        w, h, x, y = (float(m.group(i)) for i in range(1, 5))
        boxes.append((x, y, x + w, y + h))
    for m in _TEXT.finditer(body):
        x, y, sz = (float(m.group(i)) for i in range(1, 4))
        content = m.group(4)
        # <text> renders left-anchored from (x, y) where y is the
        # baseline.  Approximate width via char count × 0.6 × size,
        # height via size.  text-anchor="middle" centers around x.
        w_approx = max(20.0, len(content) * sz * 0.6)
        h_approx = sz * 1.2
        # Default anchor = start (left); most labels here use middle.
        boxes.append((x - w_approx / 2, y - h_approx,
                      x + w_approx / 2, y))
    if not boxes:
        return None
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _balanced_g_block(text: str, start: int) -> str:
    """Return body between ``<g ...>`` at ``start`` and its matching
    closing ``</g>``, balancing nested ``<g>`` tags."""
    depth = 0
    i = start
    while i < len(text):
        if text.startswith("<g", i):
            depth += 1
            j = text.find(">", i)
            i = (j + 1) if j > 0 else (i + 2)
            continue
        if text.startswith("</g>", i):
            depth -= 1
            i += 4
            if depth == 0:
                return text[start:i]
            continue
        i += 1
    return text[start:]


_TITLE_RE = re.compile(r"<title>([^<]+)</title>")


def parse_svg(svg_path: Path, engine: str):
    """Returns (nodes, clusters) where each is dict[name] = bbox."""
    text = svg_path.read_text(encoding="utf-8", errors="replace")
    nodes = {}
    clusters = {}
    if engine == "c":
        # Walk all <g id="..." ...> tags, extract balanced block,
        # classify by class= attribute.
        for m in re.finditer(
                r'<g id="([^"]+)"\s+class="(node|cluster)"[^>]*>',
                text):
            block_id, kind = m.group(1), m.group(2)
            block = _balanced_g_block(text, m.start())
            tm = _TITLE_RE.search(block)
            if not tm:
                continue
            name = (tm.group(1)
                    .replace("&#45;", "-")
                    .replace("&gt;", ">")
                    .replace("&amp;", "&"))
            # Skip edge titles (they contain "->" after html unescape).
            if "->" in name:
                continue
            bb = _bbox_from_body(block)
            if bb is None:
                continue
            if kind == "node":
                nodes[name] = bb
            else:
                clusters[name] = bb
    else:  # py
        for m in _PY_CLUST_BLOCK.finditer(text):
            name, body = m.group(1), m.group(2)
            bb = _bbox_from_body(body)
            if bb:
                clusters[name] = bb
        for m in _PY_NODE_BLOCK.finditer(text):
            name, body = m.group(1), m.group(2)
            bb = _bbox_from_body(body)
            if bb:
                nodes[name] = bb
    return nodes, clusters


# ─── Analysis ────────────────────────────────────────────────

def _bb_center_y(bb):
    return (bb[1] + bb[3]) / 2


def _bb_w(bb):
    return bb[2] - bb[0]


def _bb_h(bb):
    return bb[3] - bb[1]


def _overlap(a, b, slop=0.0):
    """True iff bboxes overlap by more than ``slop`` in BOTH axes."""
    return not (a[2] - slop <= b[0] or b[2] - slop <= a[0] or
                a[3] - slop <= b[1] or b[3] - slop <= a[1])


def _overlap_area(a, b):
    if not _overlap(a, b):
        return 0.0
    return (min(a[2], b[2]) - max(a[0], b[0])) * \
           (min(a[3], b[3]) - max(a[1], b[1]))


def rank_buckets(nodes, tol=10.0):
    """Group nodes into rank buckets by Y center.  Two nodes share a
    rank if their Y centers are within ``tol`` points."""
    sorted_items = sorted(nodes.items(), key=lambda x: _bb_center_y(x[1]))
    buckets = []  # list of (avg_y, [(name, bbox), ...])
    for name, bb in sorted_items:
        cy = _bb_center_y(bb)
        if buckets and abs(cy - buckets[-1][0]) < tol:
            avg_y, items = buckets[-1]
            items.append((name, bb))
            buckets[-1] = (
                (avg_y * (len(items) - 1) + cy) / len(items),
                items,
            )
        else:
            buckets.append((cy, [(name, bb)]))
    return buckets


def _cluster_membership(dot_path):
    """Map cluster_name → set(member node names), recursing through
    nested subgraphs.  ``graph.subgraphs`` is a dict-like of
    {name: Graph}; ``graph.nodes`` is a dict-like of
    {name: Node}."""
    from gvpy.grammar.gv_reader import read_dot_file
    g = read_dot_file(str(dot_path))
    out: dict[str, set[str]] = {}

    def _walk(graph):
        subs = getattr(graph, "subgraphs", None)
        if not subs:
            return
        for sg_name, sg in subs.items():
            if sg_name.startswith("cluster"):
                # ``sg.nodes`` is dict-like of {node_name: Node}.
                node_dict = getattr(sg, "nodes", {}) or {}
                if hasattr(node_dict, "keys"):
                    out[sg_name] = set(node_dict.keys())
                else:
                    out[sg_name] = set(node_dict)
            _walk(sg)
    _walk(g)
    return out


def report_structural(c_nodes, p_nodes):
    """Compare rank-bucketing between C and Py."""
    print("=" * 70)
    print("  Structural comparison (rank buckets)")
    print("=" * 70)
    c_buckets = rank_buckets(c_nodes)
    p_buckets = rank_buckets(p_nodes)
    print(f"  C  detected {len(c_buckets)} rank buckets")
    print(f"  Py detected {len(p_buckets)} rank buckets")
    if len(c_buckets) != len(p_buckets):
        print(f"  ✗ rank count differs!")
    else:
        print(f"  ✓ same rank count")

    # Compute rank-Y SPACING (gaps), since C uses negative Y (top-up)
    # and Py uses positive Y (top-down).  Ratio of spacings is more
    # meaningful than ratio of absolute Y.
    print()
    print(f"  {'rank':>4}  {'C_y':>8}  {'Py_y':>8}  "
          f"{'C_gap':>7}  {'Py_gap':>7}  {'gap_r':>5}  "
          f"{'C_n':>4}  {'Py_n':>4}  {'shared':>6}")
    prev_c, prev_p = None, None
    gaps_c, gaps_p = [], []
    for i in range(min(len(c_buckets), len(p_buckets))):
        c_y, c_items = c_buckets[i]
        p_y, p_items = p_buckets[i]
        c_names = {n for n, _ in c_items}
        p_names = {n for n, _ in p_items}
        shared = len(c_names & p_names)
        c_gap = abs(c_y - prev_c) if prev_c is not None else 0.0
        p_gap = abs(p_y - prev_p) if prev_p is not None else 0.0
        ratio = (p_gap / c_gap) if c_gap > 0 else 0.0
        if c_gap > 0:
            gaps_c.append(c_gap)
            gaps_p.append(p_gap)
        print(f"  {i:>4}  {c_y:>8.1f}  {p_y:>8.1f}  "
              f"{c_gap:>7.1f}  {p_gap:>7.1f}  {ratio:>5.2f}  "
              f"{len(c_items):>4}  {len(p_items):>4}  {shared:>6}")
        prev_c, prev_p = c_y, p_y
    if gaps_c:
        avg_ratio = sum(p / c for c, p in zip(gaps_c, gaps_p)) / len(gaps_c)
        print(f"  Average gap ratio (Py/C): {avg_ratio:.2f}")


def report_overlaps(label, nodes, clusters, membership, slop=0.5):
    """Detect node-node and cluster-non-member-node overlaps."""
    print()
    print("=" * 70)
    print(f"  {label} overlap audit")
    print("=" * 70)

    # Node-node overlaps (excluding cluster-member relationship).
    nn_overlaps = []
    items = list(nodes.items())
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            ni, bi = items[i]
            nj, bj = items[j]
            if _overlap(bi, bj, slop=slop):
                area = _overlap_area(bi, bj)
                nn_overlaps.append((area, ni, nj))
    nn_overlaps.sort(reverse=True)
    print(f"  node-node overlaps: {len(nn_overlaps)}")
    for area, ni, nj in nn_overlaps[:5]:
        print(f"    {ni} ∩ {nj}  area={area:.0f}")

    # Cluster-non-member-node overlaps.
    cn_overlaps = []
    for cname, cbb in clusters.items():
        members = membership.get(cname, set())
        for nname, nbb in nodes.items():
            if nname in members:
                continue
            if _overlap(nbb, cbb, slop=slop):
                area = _overlap_area(nbb, cbb)
                cn_overlaps.append((area, cname, nname))
    cn_overlaps.sort(reverse=True)
    print(f"  cluster-NON-member overlaps: {len(cn_overlaps)}")
    for area, cname, nname in cn_overlaps[:5]:
        print(f"    {cname} ∩ {nname}  area={area:.0f}")

    # Cluster-cluster overlaps (excluding parent-child).
    cc_overlaps = []
    citems = list(clusters.items())
    for i in range(len(citems)):
        for j in range(i + 1, len(citems)):
            c1n, c1b = citems[i]
            c2n, c2b = citems[j]
            m1 = membership.get(c1n, set())
            m2 = membership.get(c2n, set())
            if m1 and m2 and (m1 <= m2 or m2 <= m1):
                continue  # parent-child relation
            if _overlap(c1b, c2b, slop=slop):
                area = _overlap_area(c1b, c2b)
                cc_overlaps.append((area, c1n, c2n))
    cc_overlaps.sort(reverse=True)
    print(f"  cluster-cluster sibling overlaps: {len(cc_overlaps)}")
    for area, c1n, c2n in cc_overlaps[:5]:
        print(f"    {c1n} ∩ {c2n}  area={area:.0f}")

    return len(nn_overlaps), len(cn_overlaps), len(cc_overlaps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("c_svg", nargs="?", default="/tmp/1879_c.svg")
    ap.add_argument("py_svg", nargs="?", default="/tmp/1879_py.svg")
    ap.add_argument("--dot", default="test_data/1879.dot")
    args = ap.parse_args()

    c_path = Path(args.c_svg)
    p_path = Path(args.py_svg)
    dot_path = Path(args.dot)

    c_nodes, c_clusters = parse_svg(c_path, "c")
    p_nodes, p_clusters = parse_svg(p_path, "py")
    membership = _cluster_membership(dot_path)

    print(f"=== {dot_path.name}: C vs Py position comparison ===")
    print(f"  C  parsed {len(c_nodes)} nodes, {len(c_clusters)} clusters")
    print(f"  Py parsed {len(p_nodes)} nodes, {len(p_clusters)} clusters")

    report_structural(c_nodes, p_nodes)

    c_nn, c_cn, c_cc = report_overlaps("C", c_nodes, c_clusters, membership)
    p_nn, p_cn, p_cc = report_overlaps("Py", p_nodes, p_clusters, membership)

    print()
    print("=" * 70)
    print("  Summary table (overlap counts; lower is better)")
    print("=" * 70)
    print(f"  {'category':<32}  {'C':>6}  {'Py':>6}  {'Δ':>6}")
    print(f"  {'─'*32}  {'─'*6}  {'─'*6}  {'─'*6}")
    print(f"  {'node-node':<32}  {c_nn:>6}  {p_nn:>6}  "
          f"{p_nn - c_nn:>+6}")
    print(f"  {'cluster-non_member':<32}  {c_cn:>6}  {p_cn:>6}  "
          f"{p_cn - c_cn:>+6}")
    print(f"  {'cluster-cluster_sibling':<32}  {c_cc:>6}  {p_cc:>6}  "
          f"{p_cc - c_cc:>+6}")


if __name__ == "__main__":
    main()
