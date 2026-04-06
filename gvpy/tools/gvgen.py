"""gvgen — generate standard graphs."""

USAGE = """
Usage: gvgen [-dv?] [options]
  -c<n>   : cycle
  -g<h,w> : grid
  -k<x>   : complete
  -p<x>   : path
  -s<x>   : star
  -t<x>   : binary tree
  -w<x>   : wheel
  -d      : directed graph
  -o file : put output in file (stdout)
  -v      : verbose
  -?      : print usage
Also: petersen (named argument)
"""
from gvpy.core.graph import Graph
from gvpy.grammar.gv_writer import write_gv


def generate_complete(n: int, directed=False) -> Graph:
    """Generate complete graph K_n."""
    g = Graph(f"K{n}", directed=directed)
    g.method_init()
    names = [f"n{i}" for i in range(n)]
    for name in names:
        g.add_node(name)
    for i in range(n):
        for j in range(i + 1, n):
            g.add_edge(names[i], names[j])
    return g


def generate_cycle(n: int, directed=False) -> Graph:
    """Generate cycle graph C_n."""
    g = Graph(f"C{n}", directed=directed)
    g.method_init()
    names = [f"n{i}" for i in range(n)]
    for name in names:
        g.add_node(name)
    for i in range(n):
        g.add_edge(names[i], names[(i + 1) % n])
    return g


def generate_path(n: int, directed=False) -> Graph:
    """Generate path graph P_n."""
    g = Graph(f"P{n}", directed=directed)
    g.method_init()
    names = [f"n{i}" for i in range(n)]
    for name in names:
        g.add_node(name)
    for i in range(n - 1):
        g.add_edge(names[i], names[i + 1])
    return g


def generate_star(n: int, directed=False) -> Graph:
    """Generate star graph S_n (1 center + n leaves)."""
    g = Graph(f"S{n}", directed=directed)
    g.method_init()
    center = g.add_node("center")
    for i in range(n):
        leaf = g.add_node(f"leaf{i}")
        g.add_edge("center", f"leaf{i}")
    return g


def generate_grid(rows: int, cols: int, directed=False) -> Graph:
    """Generate grid graph rows x cols."""
    g = Graph(f"grid{rows}x{cols}", directed=directed)
    g.method_init()
    for r in range(rows):
        for c in range(cols):
            g.add_node(f"n{r}_{c}")
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                g.add_edge(f"n{r}_{c}", f"n{r}_{c+1}")
            if r + 1 < rows:
                g.add_edge(f"n{r}_{c}", f"n{r+1}_{c}")
    return g


def generate_binary_tree(depth: int, directed=True) -> Graph:
    """Generate complete binary tree of given depth."""
    g = Graph(f"tree{depth}", directed=directed)
    g.method_init()
    n = 2 ** (depth + 1) - 1
    for i in range(n):
        g.add_node(f"n{i}")
    for i in range(n):
        left = 2 * i + 1
        right = 2 * i + 2
        if left < n:
            g.add_edge(f"n{i}", f"n{left}")
        if right < n:
            g.add_edge(f"n{i}", f"n{right}")
    return g


def generate_petersen(directed=False) -> "Graph":
    """Generate the Petersen graph (10 nodes, 15 edges)."""
    g = Graph("petersen", directed=directed)
    g.method_init()
    outer = [f"o{i}" for i in range(5)]
    inner = [f"i{i}" for i in range(5)]
    for n in outer + inner:
        g.add_node(n)
    for i in range(5):
        g.add_edge(outer[i], outer[(i + 1) % 5])
        g.add_edge(outer[i], inner[i])
        g.add_edge(inner[i], inner[(i + 2) % 5])
    return g


def _dir(args):
    return args.get("directed", False) or args.get("d", False)

_GENERATORS = {
    "complete":  ("complete K_n (-k<n>)", lambda a: generate_complete(int(a.get("n", 5)), _dir(a))),
    "cycle":     ("cycle C_n (-c<n>)", lambda a: generate_cycle(int(a.get("n", 8)), _dir(a))),
    "path":      ("path P_n (-p<n>)", lambda a: generate_path(int(a.get("n", 6)), _dir(a))),
    "star":      ("star S_n (-s<n>)", lambda a: generate_star(int(a.get("n", 6)), _dir(a))),
    "grid":      ("grid RxC (-g<r,c>)", lambda a: generate_grid(int(a.get("rows", 4)),
                                                                  int(a.get("cols", 4)), _dir(a))),
    "tree":      ("binary tree depth D (-t<d>)", lambda a: generate_binary_tree(int(a.get("depth",
                                                                                a.get("n", "3"))), _dir(a))),
    "petersen":  ("Petersen graph", lambda a: generate_petersen(_dir(a))),
}


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    kind = args.get("kind", "")
    # Map n to appropriate parameter for each generator
    n = args.get("n")
    if n and "," in n:
        parts = n.split(",")
        args.setdefault("rows", parts[0])
        args.setdefault("cols", parts[1] if len(parts) > 1 else parts[0])
    elif n:
        args.setdefault("depth", n)  # for tree
    # Handle -d flag
    directed = args.get("directed", False) or args.get("d", False)

    if not kind or kind not in _GENERATORS:
        print("Available graph types:")
        for k, (desc, _) in sorted(_GENERATORS.items()):
            print(f"  {k:12s} — {desc}")
        print("\nUsage: gvtools.py gvgen <type> [n=VALUE] [rows=R] [cols=C] [depth=D]")
        return
    desc, gen_fn = _GENERATORS[kind]
    graph = gen_fn(args)
    out = write_gv(graph)
    o = args.get("o")
    if o:
        from pathlib import Path
        Path(o).write_text(out, encoding="utf-8")
    else:
        print(out, end="")
