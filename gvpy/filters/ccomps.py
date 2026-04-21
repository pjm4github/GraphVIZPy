"""ccomps — connected components filters.

Usage: gvtools.py ccomps [-sxvz] [-o template] [files]
  -s          silent (no output)
  -x          external (emit components as root graphs)
  -v          verbose
  -z          sort by size, largest first
  -o template output file template
"""

USAGE = """
Usage: ccomps [-svxz?] [-o <out template>] <files>
  -s - silent
  -x - external (emit components as root graphs)
  -v - verbose
  -z - sort by size, largest first
  -o - output file template
  -? - print usage
If no files are specified, stdin is used
"""
from collections import deque, defaultdict
from gvpy.grammar.gv_reader import read_gv, read_gv_file
from gvpy.grammar.gv_writer import write_gv


def connected_components(graph) -> list[set[str]]:
    """Find connected components. Returns list of node-name sets."""
    adj: dict[str, list[str]] = defaultdict(list)
    for name in graph.nodes:
        adj[name]
    for key, edge in graph.edges.items():
        t, h = edge.tail.name, edge.head.name
        if h not in adj[t]:
            adj[t].append(h)
        if t not in adj[h]:
            adj[h].append(t)

    visited: set[str] = set()
    components: list[set[str]] = []
    for node in adj:
        if node in visited:
            continue
        comp: set[str] = set()
        queue = deque([node])
        while queue:
            n = queue.popleft()
            if n in visited:
                continue
            visited.add(n)
            comp.add(n)
            for nb in adj.get(n, []):
                if nb not in visited:
                    queue.append(nb)
        components.append(comp)
    return components


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    graph = _load(args)
    comps = connected_components(graph)

    if args.get("z"):
        comps.sort(key=len, reverse=True)

    import sys
    if args.get("v"):
        print(f"{len(comps)} connected component(s), "
              f"{len(graph.nodes)} node(s), {len(graph.edges)} edge(s)",
              file=sys.stderr)

    if args.get("s"):
        # Silent — just print count
        print(len(comps))
        return

    if args.get("x"):
        # External: emit each component as a separate root graph in DOT
        for i, comp in enumerate(comps):
            print(f"// Component {i}: {len(comp)} nodes")
            sorted_nodes = sorted(comp)
            gtype = "digraph" if graph.directed else "graph"
            print(f"{gtype} comp_{i} {{")
            for n in sorted_nodes:
                print(f"    {n};")
            print("}")
            print()
        return

    output_lines = []
    for i, comp in enumerate(comps):
        output_lines.append(
            f"  component {i}: {len(comp)} nodes — "
            f"{', '.join(sorted(comp)[:10])}"
            f"{'...' if len(comp) > 10 else ''}")

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
