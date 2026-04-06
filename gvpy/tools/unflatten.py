"""unflatten — adjust directed graphs to improve layout aspect ratio.

Usage: gvtools.py unflatten [-f] [-l M] [-c N] [-o outfile] [files]
  -o outfile  put output in outfile (default: stdout)
  -f          adjust immediate fanout chains (requires -l)
  -l M        stagger length of leaf edges between [1, M]
  -c N        put disconnected nodes in chains of length N
"""

USAGE = """
Usage: unflatten [-f?] [-l <M>] [-c <N>] [-o <outfile>] <files>
  -o <outfile> - put output in <outfile>
  -f           - adjust immediate fanout chains
  -l <M>       - stagger length of leaf edges between [1,<M>]
  -c <N>       - put disconnected nodes in chains of length <N>
  -?           - print usage
"""
from gvpy.grammar.gv_reader import read_gv, read_gv_file
from gvpy.grammar.gv_writer import write_gv


def unflatten(graph, max_min_len=0, chain_limit=0, do_fans=False):
    """Improve aspect ratio. Returns modified graph."""
    return graph.unflatten(max_min_len, chain_limit, do_fans)


def run(args):
    if args.get("?"):
        print(USAGE)
        return
    graph = _load(args)
    ml = int(args.get("l", 0))
    cl = int(args.get("c", 0))
    fans = args.get("f", False)
    unflatten(graph, ml, cl, fans)
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
