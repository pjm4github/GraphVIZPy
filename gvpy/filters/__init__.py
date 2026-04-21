"""
Graph filters — utilities for analysis, transformation, and generation.

These are the Python equivalents of the Graphviz standalone commands
(acyclic, tred, ccomps, gc, gvgen, etc.).

Usage::

    python gvtools.py <tool> [options] [file]
    python gvtools.py gc input.gv
    python gvtools.py acyclic input.gv -o output.gv
"""

TOOLS = {
    "acyclic":    ("gvpy.filters.acyclic",    "run", "Break cycles by reversing edges"),
    "tred":       ("gvpy.filters.tred",       "run", "Transitive reduction — remove implied edges"),
    "unflatten":  ("gvpy.filters.unflatten",  "run", "Improve aspect ratio by staggering chains"),
    "ccomps":     ("gvpy.filters.ccomps",     "run", "Extract connected components"),
    "bcomps":     ("gvpy.filters.bcomps",     "run", "Extract biconnected components"),
    "sccmap":     ("gvpy.filters.sccmap",     "run", "Strongly connected components"),
    "gc":         ("gvpy.filters.gc",         "run", "Graph statistics — count nodes, edges, components"),
    "nop":        ("gvpy.filters.nop",        "run", "Canonicalize DOT — pretty-print"),
    "gvgen":      ("gvpy.filters.gvgen",      "run", "Generate standard graphs"),
    "gvcolor":    ("gvpy.filters.gvcolor",    "run", "Color nodes by component or attribute"),
    "edgepaint":  ("gvpy.filters.edgepaint",  "run", "Color edges to reduce crossing confusion"),
    "mingle":     ("gvpy.filters.mingle",     "run", "Edge bundling — reduce clutter in dense graphs"),
}


def get_tool(name: str):
    """Import and return a tool's run function."""
    import importlib
    if name not in TOOLS:
        raise KeyError(f"Unknown tool '{name}'. Available: {', '.join(sorted(TOOLS))}")
    mod_path, func_name, _ = TOOLS[name]
    mod = importlib.import_module(mod_path)
    return getattr(mod, func_name)


def list_tools() -> dict[str, str]:
    """Return {tool_name: description}."""
    return {name: desc for name, (_, _, desc) in TOOLS.items()}
