#!/usr/bin/env python3
"""
gvcli.py — Unified CLI for all GraphvizPy layout engines.

A pure-Python equivalent of the Graphviz command-line tools.  In Graphviz,
``dot``, ``neato``, ``circo``, ``fdp``, ``sfdp``, ``twopi``, ``osage``,
and ``patchwork`` are all the same binary dispatched by program name.

``gvcli.py`` mirrors this: select the layout engine with ``-K``,
or let it default to ``dot`` (hierarchical).

Pipeline::

    input → parse → layout → post-process → render → output
                      ↑
              -K dot|neato|circo|fdp|sfdp|twopi|osage|patchwork
"""
import argparse
import json
import sys
from pathlib import Path

from gvpy.engines import get_engine as _get_engine_impl, list_engines as _list_engines_impl

# Lazy imports — only loaded when needed
_gv_reader = None
_gv_writer = None
_svg_renderer = None
_png_renderer = None
_json_io = None
_gxl_io = None


def _ensure_imports():
    """Lazy-load format modules on first use."""
    global _gv_reader, _gv_writer, _svg_renderer, _png_renderer, _json_io, _gxl_io
    if _gv_reader is None:
        from gvpy.grammar import gv_reader, gv_writer
        from gvpy.render import svg_renderer, json_io, gxl_io, png_renderer
        _gv_reader = gv_reader
        _gv_writer = gv_writer
        _svg_renderer = svg_renderer
        _png_renderer = png_renderer
        _json_io = json_io
        _gxl_io = gxl_io


# ── Engine registry ────────────────────────────────


def _get_engine(name: str):
    """Import and return a layout engine class by name."""
    try:
        return _get_engine_impl(name)
    except KeyError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


_ENGINES = _list_engines_impl()


def _detect_engine_from_argv0() -> str:
    """Detect layout engine from program name (like Graphviz symlinks)."""
    prog = Path(sys.argv[0]).stem.lower()
    for engine in _ENGINES:
        if prog == engine or prog == f"{engine}py" or prog.endswith(f"_{engine}"):
            return engine
    return "dot"


# ── Format constants ──────────────────────────────

_FORMAT_EXT = {
    "json": ".json", "svg": ".svg", "png": ".png", "dot": ".gv",
    "json0": ".json", "gxl": ".gxl",
}


# ── Input ─────────────────────────────────────────


def read_graph(source, suffix=".gv"):
    """Read a graph from a file path or text, auto-detecting format.

    Accepts a ``Path`` object (format detected by extension) or a
    string (format detected by content: ``{`` → JSON, ``<`` → GXL,
    else DOT).
    """
    _ensure_imports()
    if isinstance(source, Path):
        suffix = source.suffix.lower()
        if suffix in (".json",):
            return _json_io.read_json_file(source)
        elif suffix in (".gxl", ".xml"):
            return _gxl_io.read_gxl_file(source)
        else:
            return _gv_reader.read_gv_file(source)
    # Text input (stdin)
    text = source.strip()
    if text.startswith("{"):
        return _json_io.read_json(text)
    elif text.startswith("<?xml") or text.startswith("<gxl"):
        return _gxl_io.read_gxl(text)
    else:
        return _gv_reader.read_gv(text)


# ── Layout + Render pipeline ─────────────────────


def layout_and_render(graph, fmt, engine_name="dot",
                      no_layout=False, scale=None, invert_y=False,
                      bundle=False):
    """Run layout (if needed) and produce output in the requested format.

    Parameters
    ----------
    graph : Graph
        Parsed graph object.
    fmt : str
        Output format: json, svg, dot, json0, gxl.
    engine_name : str
        Layout engine to use (default: dot).
    no_layout : bool
        If True, skip layout and use existing ``pos`` attributes.
    scale : float or None
        Scale output coordinates.
    invert_y : bool
        Invert Y axis in output.

    Returns
    -------
    str
        Rendered output text.
    """
    _ensure_imports()

    # Formats that don't need layout
    if fmt == "json0":
        return _json_io.write_json0(graph)
    if fmt == "dot" and no_layout:
        return _gv_writer.write_gv(graph)
    if fmt == "gxl" and no_layout:
        return _gxl_io.write_gxl(graph)

    # Run layout
    if not no_layout:
        EngineClass = _get_engine(engine_name)
        engine = EngineClass(graph)
        try:
            result = engine.layout()
        except NotImplementedError as e:
            print(f"Error: {e}", file=sys.stderr)
            print(f"The '{engine_name}' layout engine is not yet "
                  f"implemented. Use -Kdot for now.", file=sys.stderr)
            sys.exit(1)
    else:
        result = _result_from_attrs(graph)

    # Edge bundling (mingle post-processor)
    if bundle:
        from gvpy.tools.mingle import MingleBundler
        result = MingleBundler.bundle_result(result)

    # Post-process
    if scale is not None and scale != 1.0:
        _apply_scale(result, scale)
    if invert_y:
        _apply_invert_y(result)

    # Render
    if fmt == "svg":
        return _svg_renderer.render_svg(result)
    elif fmt == "png":
        dpi = float(graph.get_graph_attr("dpi") or
                     graph.get_graph_attr("resolution") or "72")
        return _png_renderer.render_png(result, dpi=dpi)
    elif fmt == "dot":
        return _gv_writer.write_gv(graph)
    elif fmt == "gxl":
        return _gxl_io.write_gxl(graph)
    else:
        return json.dumps(result, indent=2)


# ── Post-processing helpers ──────────────────────


def _result_from_attrs(graph):
    """Build a layout result dict from existing node ``pos`` attributes."""
    nodes = []
    for name, node in graph.nodes.items():
        pos = node.attributes.get("pos", "")
        x, y = 0.0, 0.0
        if pos and "," in pos:
            parts = pos.split(",")
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                pass
        try:
            w = float(node.attributes.get("width", "0.75")) * 72.0
        except ValueError:
            w = 54.0
        try:
            h = float(node.attributes.get("height", "0.5")) * 72.0
        except ValueError:
            h = 36.0
        entry = {"name": name, "x": x, "y": y, "width": w, "height": h}
        for attr in ("shape", "label", "color", "fillcolor", "fontcolor",
                     "fontname", "fontsize", "style", "penwidth"):
            val = node.attributes.get(attr)
            if val:
                entry[attr] = val
        nodes.append(entry)

    edges = []
    for key, edge in graph.edges.items():
        tail, head = edge.tail.name, edge.head.name
        entry = {"tail": tail, "head": head, "points": []}
        pos = edge.attributes.get("pos", "")
        if pos:
            for part in pos.split():
                part = part.lstrip("se,")
                if "," in part:
                    try:
                        px, py = part.split(",", 1)
                        entry["points"].append([float(px), float(py)])
                    except ValueError:
                        pass
        for attr in ("label", "color", "style", "penwidth", "arrowhead",
                     "arrowtail", "dir"):
            val = edge.attributes.get(attr)
            if val:
                entry[attr] = val
        edges.append(entry)

    bb_str = graph.get_graph_attr("bb") or "0,0,100,100"
    try:
        bb = [float(v) for v in bb_str.split(",")]
    except ValueError:
        bb = [0, 0, 100, 100]

    return {
        "graph": {"name": graph.name, "directed": graph.directed, "bb": bb},
        "nodes": nodes,
        "edges": edges,
    }


def _apply_scale(result, scale):
    """Scale all coordinates in a layout result."""
    for node in result.get("nodes", []):
        node["x"] *= scale
        node["y"] *= scale
        node["width"] *= scale
        node["height"] *= scale
    for edge in result.get("edges", []):
        edge["points"] = [[p[0] * scale, p[1] * scale]
                          for p in edge.get("points", [])]
        if "label_pos" in edge:
            edge["label_pos"] = [edge["label_pos"][0] * scale,
                                 edge["label_pos"][1] * scale]
    bb = result.get("graph", {}).get("bb", [0, 0, 100, 100])
    result["graph"]["bb"] = [v * scale for v in bb]
    for cl in result.get("clusters", []):
        cl["bb"] = [v * scale for v in cl.get("bb", [0, 0, 0, 0])]


def _apply_invert_y(result):
    """Invert Y axis in a layout result."""
    for node in result.get("nodes", []):
        node["y"] = -node["y"]
    for edge in result.get("edges", []):
        edge["points"] = [[p[0], -p[1]] for p in edge.get("points", [])]
        if "label_pos" in edge:
            edge["label_pos"] = [edge["label_pos"][0],
                                 -edge["label_pos"][1]]
    bb = result.get("graph", {}).get("bb", [0, 0, 100, 100])
    result["graph"]["bb"] = [bb[0], -bb[3], bb[2], -bb[1]]
    for cl in result.get("clusters", []):
        old = cl.get("bb", [0, 0, 0, 0])
        cl["bb"] = [old[0], -old[3], old[2], -old[1]]


# ── Argument parser ──────────────────────────────


def _parse_attr(spec: str) -> tuple[str, str]:
    """Parse 'name=value' into (name, value)."""
    if "=" in spec:
        k, v = spec.split("=", 1)
        return k.strip(), v.strip()
    return spec.strip(), "true"


def _build_parser() -> argparse.ArgumentParser:
    engine_list = ", ".join(sorted(_ENGINES))
    p = argparse.ArgumentParser(
        prog="gvpy",
        description=f"""\
GraphvizPy — pure-Python graph layout and rendering.

Unified CLI for all layout engines.  Select with -K:
  {engine_list}

Currently implemented: dot, neato, fdp, circo.
Post-processors: mingle (edge bundling via --bundle).
Others are stubbed and will raise NotImplementedError.

Pipeline:  input → parse → layout (-K) → [bundle] → render (-T) → output

Input formats (auto-detected by extension):
  .gv, .dot     DOT language
  .json         Graphviz JSON
  .gxl, .xml    GXL (Graph eXchange Language)
  -             stdin (format auto-detected by content)
""",
        epilog="""
examples:
  python gvcli.py input.gv -Tsvg -o out.svg     dot layout (default)
  python gvcli.py -Kdot input.gv -Tsvg          explicit dot engine
  python gvcli.py -Kcirco input.gv -Tsvg        circular layout
  python gvcli.py input.gv -Tsvg -O             auto-name → input.svg
  python gvcli.py input.gv -Tdot                DOT with layout coords
  python gvcli.py input.gv -Tjson0               structural JSON
  python gvcli.py input.gv -Tgxl                GXL XML output
  python gvcli.py input.json -Tsvg              JSON → SVG
  python gvcli.py input.gxl -Tdot               GXL → DOT
  python gvcli.py -Grankdir=LR input.gv -Tsvg   override attributes
  python gvcli.py -n input.gv -Tdot             skip layout
  echo "digraph{a->b}" | python gvcli.py -Tsvg  stdin
  python gvcli.py --list-engines                 show engines
  python gvcli.py --ui                           launch GUI wizard
  python gvcli.py --ui -Kcirco                   wizard with circo

DOT file examples:

  digraph G { a -> b -> c; a -> c; }

  digraph G {
      rankdir=LR; node [shape=box];
      A [label="Frontend"]; B [label="Backend"];
      A -> B [label="REST"];
  }
""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "files", nargs="*", metavar="FILE",
        help="Input file(s) (omit or '-' for stdin)",
    )
    p.add_argument(
        "-K", dest="engine", default=None, metavar="ENGINE",
        help=f"Layout engine: {engine_list} (default: dot)",
    )
    p.add_argument(
        "--ui", action="store_true",
        help="Launch interactive GUI wizard",
    )
    p.add_argument(
        "-T", dest="format", default="json", metavar="FORMAT",
        help="Output format: json (default), svg, png, dot, json0, gxl",
    )
    p.add_argument(
        "-o", dest="output", default=None, metavar="FILE",
        help="Write output to FILE instead of stdout",
    )
    p.add_argument(
        "-O", dest="auto_output", action="store_true",
        help="Auto-name output file: input.FORMAT",
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
    p.add_argument(
        "-n", dest="no_layout", action="store_true",
        help="Skip layout, just render (use existing pos attributes)",
    )
    p.add_argument(
        "-s", dest="scale", type=float, default=None, metavar="SCALE",
        help="Scale output coordinates",
    )
    p.add_argument(
        "-y", dest="invert_y", action="store_true",
        help="Invert Y axis",
    )
    p.add_argument(
        "--list-engines", action="store_true",
        help="List available layout engines and exit",
    )
    p.add_argument(
        "--bundle", action="store_true",
        help="Apply mingle edge bundling after layout (reduces clutter)",
    )
    p.add_argument(
        "-V", "--version", action="store_true",
        help="Print version info and exit",
    )
    p.add_argument(
        "-q", dest="quiet", action="store_true",
        help="Suppress warning messages",
    )
    p.add_argument(
        "-A", action="append", default=[], metavar="name=value",
        help="Set attribute on graph, nodes, AND edges (shorthand for -G -N -E)",
    )
    p.add_argument(
        "-x", dest="remove_isolated", action="store_true",
        help="Remove isolated nodes (nodes with no edges)",
    )
    return p


# ── Main ─────────────────────────────────────────


def main():
    parser = _build_parser()
    args = parser.parse_args()

    # Version
    if args.version:
        print("gvpy (GraphvizPy) version 0.1.0")
        print("Python port of Graphviz — https://github.com/PJMoran/GraphvizPy")
        sys.exit(0)

    # Quiet mode — suppress warnings
    if args.quiet:
        import logging
        logging.disable(logging.WARNING)

    # List engines
    if args.list_engines:
        print("Available layout engines:")
        for name, info in sorted(_ENGINES.items()):
            print(f"  {name:12s} — {info['status']}")
        sys.exit(0)

    # Determine engine
    engine_name = args.engine or _detect_engine_from_argv0()

    # Interactive wizard
    if args.ui:
        from gvpy.engines.layout.wizard import launch_wizard
        initial = args.files[0] if args.files else None
        launch_wizard(initial, engine=engine_name)
        return

    fmt = args.format.lower()

    # Determine input sources
    sources = []
    if not args.files or args.files == ["-"]:
        if sys.stdin.isatty() and not args.files:
            parser.print_help()
            sys.exit(1)
        text = sys.stdin.read()
        sources.append(("stdin", text))
    else:
        for filepath in args.files:
            path = Path(filepath)
            if not path.exists():
                print(f"Error: file not found: {path}", file=sys.stderr)
                sys.exit(1)
            sources.append((filepath, path))

    # Process each input
    for source_name, source in sources:
        graph = read_graph(source)

        # Honor layout= graph attribute if no -K flag was given
        if not args.engine:
            layout_attr = graph.get_graph_attr("layout")
            if layout_attr and layout_attr in (
                "dot", "neato", "fdp", "sfdp", "circo", "twopi",
                "osage", "patchwork",
            ):
                engine_name = layout_attr

        # Apply attribute overrides
        for spec in args.G:
            k, v = _parse_attr(spec)
            graph.set_graph_attr(k, v)
        for spec in args.N:
            k, v = _parse_attr(spec)
            for node in graph.nodes.values():
                if k not in node.attributes:
                    node.agset(k, v)
        for spec in args.E:
            k, v = _parse_attr(spec)
            for edge in graph.edges.values():
                if k not in edge.attributes:
                    edge.agset(k, v)
        # -A: apply to graph + all nodes + all edges
        for spec in args.A:
            k, v = _parse_attr(spec)
            graph.set_graph_attr(k, v)
            for node in graph.nodes.values():
                if k not in node.attributes:
                    node.agset(k, v)
            for edge in graph.edges.values():
                if k not in edge.attributes:
                    edge.agset(k, v)

        # -x: remove isolated nodes (no edges)
        if args.remove_isolated:
            connected = set()
            for key, edge in graph.edges.items():
                connected.add(edge.tail.name)
                connected.add(edge.head.name)
            isolated = [n for n in list(graph.nodes.keys())
                        if n not in connected]
            for name in isolated:
                graph.delete_node(graph.nodes[name])

        # Layout + render
        output = layout_and_render(
            graph, fmt,
            engine_name=engine_name,
            no_layout=args.no_layout,
            scale=args.scale,
            invert_y=args.invert_y,
            bundle=args.bundle,
        )

        if args.verbose:
            n = len(graph.nodes)
            e = len(graph.edges)
            s = len(graph.subgraphs)
            print(f"{source_name} [{engine_name}]: "
                  f"{n} nodes, {e} edges, {s} subgraphs",
                  file=sys.stderr)

        # Output destination — binary for PNG, text for everything else
        is_binary = isinstance(output, bytes)
        if args.output:
            if is_binary:
                Path(args.output).write_bytes(output)
            else:
                Path(args.output).write_text(output, encoding="utf-8")
        elif args.auto_output and isinstance(source, Path):
            ext = _FORMAT_EXT.get(fmt, f".{fmt}")
            out_path = Path(source).with_suffix(ext)
            if is_binary:
                out_path.write_bytes(output)
            else:
                out_path.write_text(output, encoding="utf-8")
            if args.verbose:
                print(f"  → {out_path}", file=sys.stderr)
        else:
            if is_binary:
                sys.stdout.buffer.write(output)
            else:
                print(output)


if __name__ == "__main__":
    main()
