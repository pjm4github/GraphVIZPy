#!/usr/bin/env python3
"""
dot.py — CLI for the GraphvizPy hierarchical layout engine.

A pure-Python equivalent of Graphviz ``dot``.  Parses a DOT-language file,
computes a hierarchical layout, and outputs node/edge coordinates as JSON
or SVG.
"""
import argparse
import json
import sys
from pathlib import Path

from pycode.dot.dot_reader import read_dot_file, read_dot_file_all
from pycode.dot.dot_layout import DotLayout
from pycode.dot.svg_renderer import render_svg


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dot.py",
        description="""\
GraphvizPy dot layout engine — a pure-Python equivalent of Graphviz "dot".

Reads a graph described in the DOT language (.gv or .dot file) and computes
a hierarchical layout that arranges nodes in ranks (layers), minimizes edge
crossings, and routes edges between nodes.

Input:   One or more DOT-language files (.gv, .dot)
Output:  JSON dict with node coordinates and edge routes (default)
         SVG vector image with nodes, edges, and labels (-Tsvg)

Quick start:
  1. Create a file called "graph.gv" with:
       digraph G { a -> b -> c; a -> c; }
  2. Run:   python dot.py graph.gv -Tsvg -o graph.svg
  3. Open graph.svg in a browser to see the layout.

Interactive mode:
  python dot.py --ui                       launch GUI wizard
  python dot.py --ui graph.gv              launch wizard with file loaded
""",
        epilog="""
examples:
  python dot.py input.gv                   JSON to stdout
  python dot.py input.gv -Tsvg            SVG to stdout
  python dot.py input.gv -Tsvg -o out.svg SVG to file
  python dot.py input.gv -o out.json      JSON to file
  python dot.py -Tsvg a.gv b.gv           layout multiple files
  python dot.py input.gv -Grankdir=LR     left-to-right layout
  python dot.py input.gv -Nshape=box      set default node shape
  python dot.py input.gv -Ecolor=red      set default edge color
  python dot.py input.gv -v               print summary to stderr

DOT file examples:

  Simple directed graph:
    digraph G {
        a -> b -> c;
        a -> c;
    }

  Left-to-right with labels:
    digraph G {
        rankdir=LR;
        node [shape=box];
        A [label="Frontend"];
        B [label="Backend"];
        C [label="Database"];
        A -> B [label="REST"];
        B -> C [label="SQL"];
    }

  Clusters:
    digraph G {
        subgraph cluster_ui  { label="UI";  a; b; }
        subgraph cluster_api { label="API"; c; d; }
        a -> c;
        b -> d;
    }

  Rank constraints:
    digraph G {
        { rank=same; b; c; }
        a -> b;
        a -> c;
        b -> d;
        c -> d;
    }

  Record shapes with ports:
    digraph G {
        node [shape=record];
        a [label="<h> Header|<b> Body|<f> Footer"];
        b [label="<in> Input|<out> Output"];
        a:b -> b:in;
        a:f -> b:out;
    }
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "files", nargs="*", metavar="FILE",
        help="Input DOT file(s) to layout",
    )
    p.add_argument(
        "--ui", action="store_true",
        help="Launch interactive GUI wizard",
    )
    p.add_argument(
        "-T", dest="format", default="json", metavar="FORMAT",
        help="Output format: json (default) or svg",
    )
    p.add_argument(
        "-o", dest="output", default=None, metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    p.add_argument(
        "-G", action="append", default=[], metavar="name=value",
        help="Set a graph attribute (e.g. -Grankdir=LR)",
    )
    p.add_argument(
        "-N", action="append", default=[], metavar="name=value",
        help="Set a default node attribute (e.g. -Nshape=box)",
    )
    p.add_argument(
        "-E", action="append", default=[], metavar="name=value",
        help="Set a default edge attribute (e.g. -Ecolor=red)",
    )
    p.add_argument(
        "-v", "--verbose", action="store_true",
        help="Print layout summary to stderr",
    )
    return p


def _parse_attr(spec: str) -> tuple[str, str]:
    """Parse 'name=value' into (name, value)."""
    if "=" in spec:
        k, v = spec.split("=", 1)
        return k.strip(), v.strip()
    return spec.strip(), "true"


def main():
    parser = _build_parser()
    args = parser.parse_args()

    # Interactive wizard mode
    if args.ui:
        from pycode.dot.dot_wizard import launch_wizard
        initial = args.files[0] if args.files else None
        launch_wizard(initial)
        return

    if not args.files:
        parser.print_help()
        sys.exit(1)

    fmt = args.format.lower()

    outputs = []

    for filepath in args.files:
        path = Path(filepath)
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)

        graph = read_dot_file(path)

        # Apply -G overrides
        for spec in args.G:
            k, v = _parse_attr(spec)
            graph.set_graph_attr(k, v)

        # Apply -N defaults to all nodes
        for spec in args.N:
            k, v = _parse_attr(spec)
            for node in graph.nodes.values():
                if k not in node.attributes:
                    node.agset(k, v)

        # Apply -E defaults to all edges
        for spec in args.E:
            k, v = _parse_attr(spec)
            for edge in graph.edges.values():
                if k not in edge.attributes:
                    edge.agset(k, v)

        result = DotLayout(graph).layout()

        if args.verbose:
            n = len(result["nodes"])
            e = len(result["edges"])
            c = len(result.get("clusters", []))
            print(f"{path.name}: {n} nodes, {e} edges, {c} clusters",
                  file=sys.stderr)

        if fmt == "svg":
            outputs.append(render_svg(result))
        else:
            outputs.append(json.dumps(result, indent=2))

    combined = "\n".join(outputs)

    if args.output:
        Path(args.output).write_text(combined, encoding="utf-8")
    else:
        print(combined)


if __name__ == "__main__":
    main()
