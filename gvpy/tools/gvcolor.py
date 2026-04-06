"""gvcolor — color nodes by connected component or attribute."""

USAGE = """
Usage: gvcolor [-?] [mode=component|degree] <files>
  mode=component - color by connected component (default)
  mode=degree    - color by node degree
  -? - print usage
If no files are specified, stdin is used
"""
from gvpy.grammar.gv_reader import read_gv, read_gv_file
from gvpy.grammar.gv_writer import write_gv
from gvpy.tools.ccomps import connected_components

_COLORS = [
    "red", "blue", "green", "orange", "purple", "brown",
    "cyan", "magenta", "olive", "teal", "navy", "maroon",
    "lime", "aqua", "fuchsia", "silver", "coral", "salmon",
]


def color_by_component(graph):
    """Assign colors to nodes based on their connected component."""
    comps = connected_components(graph)
    for i, comp in enumerate(comps):
        color = _COLORS[i % len(_COLORS)]
        for name in comp:
            node = graph.nodes.get(name)
            if node:
                node.agset("color", color)
                node.agset("fillcolor", color)
                if not node.attributes.get("style"):
                    node.agset("style", "filled")


def color_by_degree(graph):
    """Color nodes by degree (darker = higher degree)."""
    from collections import defaultdict
    degree: dict[str, int] = defaultdict(int)
    for key, edge in graph.edges.items():
        degree[edge.tail.name] += 1
        degree[edge.head.name] += 1
    max_deg = max(degree.values()) if degree else 1
    for name, node in graph.nodes.items():
        d = degree.get(name, 0)
        intensity = int(255 * (1 - d / max_deg))
        color = f"#{intensity:02x}{intensity:02x}ff"
        node.agset("fillcolor", color)
        if not node.attributes.get("style"):
            node.agset("style", "filled")


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    graph = _load(args)
    mode = args.get("mode", "component")
    if mode == "degree":
        color_by_degree(graph)
    else:
        color_by_component(graph)
    print(write_gv(graph), end="")


def _load(args):
    f = args.get("file")
    if f and f != "-":
        from pathlib import Path
        return read_gv_file(Path(f))
    import sys
    return read_gv(sys.stdin.read())
