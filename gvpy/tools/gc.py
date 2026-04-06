"""gc — count graph components.

Usage: gvtools.py gc [-necCaDUrsv] [files]
  -n  print number of nodes
  -e  print number of edges
  -c  print number of connected components
  -C  print number of clusters
  -a  print all counts
  -D  only directed graphs
  -U  only undirected graphs
  -r  recursively analyze subgraphs
  -s  silent
  -v  verbose

By default, prints nodes and edges.
"""

USAGE = """
Usage: gc [-necCaDUrsv?] <files>
  -n - print number of nodes
  -e - print number of edges
  -c - print number of connected components
  -C - print number of clusters
  -a - print all counts
  -D - only directed graphs
  -U - only undirected graphs
  -r - recursively analyze subgraphs
  -s - silent
  -v - verbose
  -? - print usage
By default, gc prints nodes and edges.
If no files are specified, stdin is used
"""
from gvpy.grammar.gv_reader import read_gv, read_gv_file
from gvpy.tools.ccomps import connected_components


def graph_stats(graph, recurse=False) -> dict:
    """Return graph statistics."""
    comps = connected_components(graph)
    stats = {
        "name": graph.name,
        "directed": graph.directed,
        "strict": graph.strict,
        "nodes": len(graph.nodes),
        "edges": len(graph.edges),
        "subgraphs": len(graph.subgraphs),
        "components": len(comps),
        "clusters": sum(1 for s in graph.subgraphs
                        if s.startswith("cluster")),
        "isolated": sum(1 for c in comps if len(c) == 1),
    }
    if recurse:
        stats["sub_stats"] = []
        for name, sub in graph.subgraphs.items():
            stats["sub_stats"].append(graph_stats(sub, recurse=True))
    return stats


def _count_clusters(graph) -> int:
    """Count cluster subgraphs recursively."""
    count = 0
    for name, sub in graph.subgraphs.items():
        if name.startswith("cluster"):
            count += 1
        count += _count_clusters(sub)
    return count


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    graph = _load(args)

    # Filter by direction
    if args.get("D") and not graph.directed:
        return
    if args.get("U") and graph.directed:
        return

    s = graph_stats(graph, recurse=args.get("r", False))

    if args.get("s"):
        return

    # Determine what to print
    show_n = args.get("n", False)
    show_e = args.get("e", False)
    show_c = args.get("c", False)
    show_C = args.get("C", False)
    show_a = args.get("a", False)

    # Default: nodes and edges
    if not any([show_n, show_e, show_c, show_C, show_a]):
        show_n = show_e = True

    if show_a:
        show_n = show_e = show_c = show_C = True

    parts = []
    if show_n:
        parts.append(f"{s['nodes']} nodes")
    if show_e:
        parts.append(f"{s['edges']} edges")
    if show_c:
        parts.append(f"{s['components']} components")
    if show_C:
        clusters = _count_clusters(graph)
        parts.append(f"{clusters} clusters")

    name = s["name"] or "(stdin)"
    print(f"{name}: {', '.join(parts)}")

    if args.get("v"):
        import sys
        print(f"  Type: {'directed' if s['directed'] else 'undirected'}"
              f"{' strict' if s['strict'] else ''}", file=sys.stderr)
        if s["isolated"]:
            print(f"  Isolated: {s['isolated']}", file=sys.stderr)

    if args.get("r") and s.get("sub_stats"):
        for ss in s["sub_stats"]:
            parts = [f"{ss['nodes']} nodes", f"{ss['edges']} edges"]
            print(f"  {ss['name']}: {', '.join(parts)}")


def _load(args):
    f = args.get("file")
    if f and f != "-":
        from pathlib import Path
        return read_gv_file(Path(f))
    import sys
    return read_gv(sys.stdin.read())
