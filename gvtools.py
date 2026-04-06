#!/usr/bin/env python3
"""
gvtools.py — Graph utility tools (analysis, transformation, generation).

Python equivalents of the Graphviz standalone commands.

Usage::

    python gvtools.py <tool> [options] [file]
    python gvtools.py gc input.gv
    python gvtools.py acyclic -v input.gv
    python gvtools.py sccmap -d input.gv
    python gvtools.py gvgen -k 8
    python gvtools.py --list
"""
import sys

from gvpy.tools import TOOLS, get_tool

# Short flags that take a value argument (next arg is the value)
_VALUE_FLAGS = {"o", "l", "c", "X", "n", "N", "a", "i", "k", "K", "m", "p", "r", "T"}

# Short flags that are boolean (no value)
_BOOL_FLAGS = {"v", "n", "s", "S", "r", "x", "t", "d", "f", "p",
               "z", "e", "a", "D", "U", "C", "?"}


def _parse_tool_args(argv: list[str], tool_name: str) -> dict:
    """Parse tool-specific arguments into a dict.

    Handles:
      -v, -n, -s, etc.        → args["v"] = True
      -o file, -l 3, -c 5     → args["o"] = "file"
      -k8, -c12, -p5          → gvgen style: args["kind"]="complete", etc.
      key=value               → args["key"] = "value"
      positional              → args["file"] or args["kind"]
    """
    args: dict = {}
    positionals: list[str] = []
    i = 0

    # gvgen uses single-letter flags with attached values
    is_gvgen = (tool_name == "gvgen")

    while i < len(argv):
        arg = argv[i]

        if arg == "-":
            positionals.append(arg)
        elif arg == "--all":
            args["all"] = True
        elif "=" in arg and not arg.startswith("-"):
            k, v = arg.split("=", 1)
            args[k] = v
        elif is_gvgen and len(arg) >= 2 and arg[0] == "-" and arg[1].isalpha():
            # gvgen: -k8 means kind=complete, n=8
            flag = arg[1]
            value = arg[2:] if len(arg) > 2 else ""
            _GVGEN_MAP = {
                "k": "complete", "c": "cycle", "p": "path", "s": "star",
                "w": "wheel", "t": "tree", "m": "mesh",
            }
            if flag in _GVGEN_MAP:
                args["kind"] = _GVGEN_MAP[flag]
                if value:
                    args["n"] = value
            elif flag == "g":
                args["kind"] = "grid"
                if "," in value:
                    r, c = value.split(",", 1)
                    args["rows"] = r
                    args["cols"] = c
                elif value:
                    args["rows"] = args["cols"] = value
            elif flag == "b":
                args["kind"] = "bipartite"
                if value:
                    args["n"] = value
            elif flag == "d":
                args["directed"] = True
            elif flag == "o":
                if value:
                    args["o"] = value
                elif i + 1 < len(argv):
                    i += 1
                    args["o"] = argv[i]
            elif flag == "n" and value:
                args["prefix"] = value
            elif flag == "N" and value:
                args["graph_name"] = value
            elif flag in _BOOL_FLAGS:
                args[flag] = True
            else:
                args[flag] = value or True
        elif arg.startswith("-") and len(arg) >= 2:
            # Standard short flags
            flag = arg[1]
            rest = arg[2:]

            if flag in _BOOL_FLAGS and not rest:
                args[flag] = True
            elif flag in _BOOL_FLAGS and rest:
                # Multiple bool flags: -vr → v=True, r=True
                args[flag] = True
                for ch in rest:
                    if ch in _BOOL_FLAGS:
                        args[ch] = True
            elif flag in _VALUE_FLAGS:
                if rest:
                    args[flag] = rest
                elif i + 1 < len(argv):
                    i += 1
                    args[flag] = argv[i]
            else:
                # Unknown flag — store as bool
                args[flag] = True
        else:
            positionals.append(arg)

        i += 1

    # Assign positionals
    if tool_name == "gvgen":
        if positionals and "kind" not in args:
            args["kind"] = positionals[0]
    else:
        if positionals:
            args["file"] = positionals[0]

    return args


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("--help", "-h", "--list", "-?"):
        print("gvtools — GraphvizPy graph utilities\n")
        print("Usage: python gvtools.py <tool> [options] [file]\n")
        print("Available tools:")
        for name, (_, _, desc) in sorted(TOOLS.items()):
            print(f"  {name:12s} — {desc}")
        print()
        print("Examples:")
        print("  python gvtools.py gc input.gv              # graph statistics")
        print("  python gvtools.py gc -a input.gv           # all counts")
        print("  python gvtools.py gc -nec input.gv         # nodes + edges + components")
        print("  python gvtools.py acyclic -v input.gv      # break cycles, verbose")
        print("  python gvtools.py acyclic -n input.gv      # check only, no output")
        print("  python gvtools.py tred -r input.gv         # show removed edges")
        print("  python gvtools.py ccomps -z input.gv       # components sorted by size")
        print("  python gvtools.py bcomps -t input.gv       # block-cutpoint tree")
        print("  python gvtools.py sccmap -s input.gv       # statistics only")
        print("  python gvtools.py sccmap -d input.gv       # include single-node SCCs")
        print("  python gvtools.py unflatten -l 3 input.gv  # stagger leaves")
        print("  python gvtools.py unflatten -f -l 4 input.gv  # with fanout")
        print("  python gvtools.py nop input.gv             # pretty-print DOT")
        print("  python gvtools.py nop -p input.gv          # parse-only (validate)")
        print("  python gvtools.py gvgen -k8                # complete K8")
        print("  python gvtools.py gvgen -c12               # cycle C12")
        print("  python gvtools.py gvgen -g4,6              # 4x6 grid")
        print("  python gvtools.py gvgen -t4                # binary tree depth 4")
        print("  python gvtools.py gvgen -s6 -d             # directed star S6")
        print("  python gvtools.py gvgen petersen           # Petersen graph")
        print("  python gvtools.py gvcolor input.gv         # color by component")
        print("  python gvtools.py gvcolor mode=degree input.gv")
        print("  python gvtools.py edgepaint input.gv       # color crossing edges")
        sys.exit(0)

    tool_name = sys.argv[1]

    try:
        run_fn = get_tool(tool_name)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    args = _parse_tool_args(sys.argv[2:], tool_name)

    try:
        run_fn(args)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
