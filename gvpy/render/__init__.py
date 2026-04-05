"""
Rendering and format I/O — engine-agnostic output modules.

These modules convert layout results (or Graph objects) to/from
various output formats. They are shared across all layout engines.

Supported formats:

- **SVG** — ``render_svg(layout_dict)`` renders positioned nodes/edges
- **JSON** — Graphviz-compatible ``json``/``json0`` graph interchange
- **GXL** — Graph eXchange Language (XML-based) read/write

For GV/DOT reading and writing, see ``gvpy.grammar``.
"""
from .svg_renderer import render_svg, render_svg_file
from .json_io import (
    read_json, read_json_file, write_json, write_json0,
    write_json_file,
)
from .gxl_io import (
    read_gxl, read_gxl_file, read_gxl_all, write_gxl,
    write_gxl_file,
)
