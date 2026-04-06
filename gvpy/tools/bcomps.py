"""bcomps — biconnected components filter.

Usage: gvtools.py bcomps [-stvx] [-o template] [files]
  -o template  output file template
  -s           don't print components (silent)
  -t           emit block-cutpoint tree
  -v           verbose
  -x           external (emit blocks as root graphs)
"""

USAGE = """
Usage: bcomps [-stvx?] [-o <out template>] <files>
  -o - output file template
  -s - don't print components
  -t - emit block-cutpoint tree
  -v - verbose
  -x - external (emit blocks as root graphs)
  -? - print usage
If no files are specified, stdin is used
"""
from collections import defaultdict
from gvpy.grammar.gv_reader import read_gv, read_gv_file


def biconnected_components(graph) -> tuple[list[set[str]], set[str]]:
    """Find biconnected components and articulation points.
    Returns (list of node-name sets, set of articulation point names).
    """
    adj: dict[str, list[str]] = defaultdict(list)
    for name in graph.nodes:
        adj[name]
    for key, edge in graph.edges.items():
        t, h = edge.tail.name, edge.head.name
        if h not in adj[t]:
            adj[t].append(h)
        if t not in adj[h]:
            adj[h].append(t)

    disc, low, parent = {}, {}, {}
    timer = [0]
    edge_stack: list[tuple[str, str]] = []
    blocks: list[set[str]] = []
    art_points: set[str] = set()

    def _dfs(u):
        disc[u] = low[u] = timer[0]
        timer[0] += 1
        child_count = 0
        for v in adj.get(u, []):
            if v not in disc:
                child_count += 1
                parent[v] = u
                edge_stack.append((u, v))
                _dfs(v)
                low[u] = min(low[u], low[v])
                is_root = parent.get(u) is None
                if (is_root and child_count > 1) or \
                   (not is_root and low[v] >= disc[u]):
                    art_points.add(u)
                    block_nodes = set()
                    while edge_stack and edge_stack[-1] != (u, v):
                        e = edge_stack.pop()
                        block_nodes.add(e[0])
                        block_nodes.add(e[1])
                    if edge_stack:
                        e = edge_stack.pop()
                        block_nodes.add(e[0])
                        block_nodes.add(e[1])
                    blocks.append(block_nodes)
            elif v != parent.get(u) and disc[v] < disc[u]:
                edge_stack.append((u, v))
                low[u] = min(low[u], disc[v])

    for node in adj:
        if node not in disc:
            parent[node] = None
            _dfs(node)
            if edge_stack:
                block_nodes = set()
                while edge_stack:
                    e = edge_stack.pop()
                    block_nodes.add(e[0])
                    block_nodes.add(e[1])
                blocks.append(block_nodes)

    covered = set()
    for b in blocks:
        covered.update(b)
    for n in graph.nodes:
        if n not in covered:
            blocks.append({n})

    return blocks, art_points


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    graph = _load(args)
    blocks, art = biconnected_components(graph)

    import sys
    if args.get("v"):
        print(f"{len(blocks)} biconnected component(s), "
              f"{len(art)} articulation point(s)", file=sys.stderr)

    if args.get("s"):
        print(len(blocks))
        return

    if args.get("t"):
        # Emit block-cutpoint tree
        print("Block-cutpoint tree:")
        for i, block in enumerate(blocks):
            cut_in_block = block & art
            print(f"  block_{i} ({len(block)} nodes)"
                  f" cuts: {', '.join(sorted(cut_in_block)) if cut_in_block else 'none'}")
        return

    if args.get("x"):
        # External: emit each block as a root graph
        gtype = "digraph" if graph.directed else "graph"
        for i, block in enumerate(blocks):
            print(f"{gtype} block_{i} {{")
            for n in sorted(block):
                print(f"    {n};")
            print("}")
            print()
        return

    output_lines = []
    if art:
        output_lines.append(f"Articulation points: {', '.join(sorted(art))}")
    for i, block in enumerate(blocks):
        output_lines.append(
            f"  block {i}: {len(block)} nodes — "
            f"{', '.join(sorted(block)[:10])}"
            f"{'...' if len(block) > 10 else ''}")
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
