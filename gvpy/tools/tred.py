"""tred — transitive reduction filter for directed graphs.

Usage: gvtools.py tred [-vr] [-o outfile] [files]
  -o FILE  redirect output to FILE (default: stdout)
  -v       verbose (report to stderr)
  -r       print removed edges to stderr
"""

USAGE = """
Usage: tred [-vr?] <files>
  -o FILE - redirect output (default to stdout)
  -v      - verbose (to stderr)
  -r      - print removed edges to stderr
  -?      - print usage
If no files are specified, stdin is used
"""
from gvpy.grammar.gv_reader import read_gv, read_gv_file
from gvpy.grammar.gv_writer import write_gv


def tred(graph):
    """Remove transitively implied edges. Returns count removed."""
    return graph.tred()


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    graph = _load(args)
    import sys
    n = tred(graph)
    if args.get("v"):
        print(f"tred: removed {n} transitive edge(s)", file=sys.stderr)
    if args.get("r") and n:
        print(f"tred: {n} edge(s) removed", file=sys.stderr)
    _output(write_gv(graph), args)


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
