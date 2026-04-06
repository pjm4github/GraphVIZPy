"""acyclic — make directed graph acyclic by reversing edges.

Usage: gvtools.py acyclic [-nv] [-o outfile] [file]
  -o outfile  write output to file (default: stdout)
  -n          do not output graph (just report)
  -v          verbose (report to stderr)
"""

USAGE = """
Usage: acyclic [-nv?] [-o outfile] <file>
  -o <file> - put output in <file>
  -n        - do not output graph
  -v        - verbose
  -?        - print usage
"""
from gvpy.grammar.gv_reader import read_gv, read_gv_file
from gvpy.grammar.gv_writer import write_gv


def acyclic(graph):
    """Break cycles in a directed graph. Returns count of reversed edges."""
    return graph.acyclic()


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    graph = _load(args)
    n = acyclic(graph)
    import sys
    if args.get("v"):
        if n:
            print(f"acyclic: reversed {n} edge(s)", file=sys.stderr)
        else:
            print("acyclic: graph is already acyclic", file=sys.stderr)
    if not args.get("n"):
        out = write_gv(graph)
        _output(out, args)


def _load(args):
    f = args.get("file")
    if f and f != "-":
        from pathlib import Path
        return read_gv_file(Path(f))
    import sys
    return read_gv(sys.stdin.read())


def _output(text, args):
    o = args.get("o")
    if o:
        from pathlib import Path
        Path(o).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
