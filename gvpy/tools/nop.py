"""nop — pretty-print / canonicalize DOT graph file.

Usage: gvtools.py nop [-p] [files]
  -p  check for valid DOT (parse but don't output)
"""

USAGE = """
Usage: nop [-p?] <files>
  -p - check for valid DOT (parse but don't output)
  -? - print usage
If no files are specified, stdin is used
"""
from gvpy.grammar.gv_reader import read_gv, read_gv_file, GVParseError
from gvpy.grammar.gv_writer import write_gv


def canonicalize(graph) -> str:
    """Pretty-print a graph as canonical DOT text."""
    return write_gv(graph)


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    import sys
    if args.get("p"):
        # Parse-only mode: check for valid DOT
        try:
            graph = _load(args)
            print(f"Valid DOT: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
        except GVParseError as e:
            print(f"Parse error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    graph = _load(args)
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
