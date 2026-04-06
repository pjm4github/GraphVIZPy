"""edgepaint — color edges to reduce crossing confusion.

Assigns distinct colors to edges that cross each other, so that
edge crossings are easier to trace visually.
"""

USAGE = """
Usage: edgepaint [-v?] [-o fname] <file>
  --angle=a        - min crossing angle in degrees (default 15)
  --color_scheme=c - palette: rgb, gray, lab, or hex list
  --share_endpoint - edges sharing endpoints not conflicting
  -v               - verbose
  -o fname         - write output to file (stdout)
  -? - print usage
"""
import math
from collections import defaultdict
from gvpy.grammar.gv_reader import read_gv, read_gv_file
from gvpy.grammar.gv_writer import write_gv

_EDGE_COLORS = [
    "#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
    "#a65628", "#f781bf", "#999999", "#66c2a5", "#fc8d62",
    "#8da0cb", "#e78ac3", "#a6d854", "#ffd92f", "#e5c494",
]


def edgepaint(graph):
    """Assign distinct colors to edges that cross, using a greedy
    graph coloring on the edge intersection graph.

    Requires nodes to have pos attributes (run layout first).
    """
    # Extract edge endpoints
    edges = []
    edge_keys = []
    for key, edge in graph.edges.items():
        t, h = edge.tail, edge.head
        tp = t.attributes.get("pos", "0,0").split(",") if t else ["0", "0"]
        hp = h.attributes.get("pos", "0,0").split(",") if h else ["0", "0"]
        try:
            x1, y1 = float(tp[0]), float(tp[1])
            x2, y2 = float(hp[0]), float(hp[1])
        except (ValueError, IndexError):
            x1 = y1 = x2 = y2 = 0
        edges.append((x1, y1, x2, y2))
        edge_keys.append(key)

    # Build edge crossing graph
    N = len(edges)
    crosses: dict[int, set[int]] = defaultdict(set)
    for i in range(N):
        for j in range(i + 1, N):
            if _segments_cross(edges[i], edges[j]):
                crosses[i].add(j)
                crosses[j].add(i)

    # Greedy coloring
    color_assignment: dict[int, int] = {}
    for i in range(N):
        used = {color_assignment[nb] for nb in crosses[i] if nb in color_assignment}
        c = 0
        while c in used:
            c += 1
        color_assignment[i] = c

    # Apply colors
    for i, key in enumerate(edge_keys):
        c = color_assignment.get(i, 0)
        color = _EDGE_COLORS[c % len(_EDGE_COLORS)]
        graph.edges[key].agset("color", color)


def _segments_cross(seg1, seg2) -> bool:
    """Test if two line segments cross (proper intersection)."""
    x1, y1, x2, y2 = seg1
    x3, y3, x4, y4 = seg2

    def _ccw(ax, ay, bx, by, cx, cy):
        return (cx - ax) * (by - ay) - (bx - ax) * (cy - ay)

    d1 = _ccw(x3, y3, x4, y4, x1, y1)
    d2 = _ccw(x3, y3, x4, y4, x2, y2)
    d3 = _ccw(x1, y1, x2, y2, x3, y3)
    d4 = _ccw(x1, y1, x2, y2, x4, y4)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    graph = _load(args)
    edgepaint(graph)
    import sys
    if args.get("v"):
        # Count how many edges got colored
        colored = sum(1 for e in graph.edges.values()
                      if e.attributes.get("color"))
        print(f"edgepaint: colored {colored} edge(s)", file=sys.stderr)
    out = write_gv(graph)
    o = args.get("o")
    if o:
        from pathlib import Path
        Path(o).write_text(out, encoding="utf-8")
    else:
        print(out, end="")


def _load(args):
    f = args.get("file")
    if f and f != "-":
        from pathlib import Path
        return read_gv_file(Path(f))
    import sys
    return read_gv(sys.stdin.read())
