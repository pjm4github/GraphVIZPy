"""sccmap — extract strongly connected components of directed graphs.

Usage: gvtools.py sccmap [-sSdv] [-o outfile] [files]
  -s          only produce statistics (no component output)
  -S          silent (no stderr output)
  -d          allow degenerate components (single nodes)
  -o outfile  write to outfile (default: stdout)
  -v          verbose
"""

USAGE = """
Usage: sccmap [-sSdv?] [-o <outfile>] <files>
  -s          - only produce statistics
  -S          - silent
  -d          - allow degenerate components
  -o <outfile> - write to <outfile> (stdout)
  -v          - verbose
  -? - print usage
If no files are specified, stdin is used
"""
from collections import defaultdict
from gvpy.grammar.gv_reader import read_gv, read_gv_file


def strongly_connected_components(graph) -> list[set[str]]:
    """Find strongly connected components using Tarjan's algorithm."""
    adj: dict[str, list[str]] = defaultdict(list)
    for name in graph.nodes:
        adj[name]
    for key, edge in graph.edges.items():
        adj[edge.tail.name].append(edge.head.name)

    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    index: dict[str, int] = {}
    lowlink: dict[str, int] = {}
    sccs: list[set[str]] = []

    def _strongconnect(v):
        index[v] = lowlink[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)

        for w in adj.get(v, []):
            if w not in index:
                _strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in on_stack:
                lowlink[v] = min(lowlink[v], index[w])

        if lowlink[v] == index[v]:
            scc: set[str] = set()
            while True:
                w = stack.pop()
                on_stack.discard(w)
                scc.add(w)
                if w == v:
                    break
            sccs.append(scc)

    for node in adj:
        if node not in index:
            _strongconnect(node)

    return sccs


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    graph = _load(args)
    sccs = strongly_connected_components(graph)
    show_degenerate = args.get("d", False)

    if not show_degenerate:
        display = [s for s in sccs if len(s) > 1]
    else:
        display = sccs

    import sys

    if args.get("s"):
        # Statistics only
        non_trivial = sum(1 for s in sccs if len(s) > 1)
        print(f"{len(sccs)} strongly connected component(s)")
        print(f"{non_trivial} non-trivial (size > 1)")
        print(f"{len(graph.nodes)} node(s), {len(graph.edges)} edge(s)")
        return

    if not args.get("S"):
        non_trivial = sum(1 for s in sccs if len(s) > 1)
        print(f"{len(sccs)} SCC(s) total, {non_trivial} non-trivial",
              file=sys.stderr if args.get("v") else sys.stdout)

    output_lines = []
    for i, scc in enumerate(display):
        output_lines.append(
            f"  SCC {i}: {len(scc)} nodes — "
            f"{', '.join(sorted(scc)[:10])}"
            f"{'...' if len(scc) > 10 else ''}")
    text = "\n".join(output_lines)
    o = args.get("o")
    if o:
        from pathlib import Path
        Path(o).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def _load(args):
    f = args.get("file")
    if f and f != "-":
        from pathlib import Path
        return read_gv_file(Path(f))
    import sys
    return read_gv(sys.stdin.read())
