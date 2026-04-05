# GraphvizPy

A pure-Python implementation of the Graphviz graph visualization toolkit, featuring an ANTLR4-based DOT language parser, multiple layout engines, and an interactive PyQt6 GUI.

## Purpose

- Port the Graphviz C codebase to Python 3.13+ for exploration and modernization
- Replace C data structures with Python dicts, sets, and typing constructs
- Provide an interactive GUI for graph editing and layout visualization
- Integrate with the [pictosync](https://github.com/pjm4github/pictosync) project for rendering

## Quick Start

### Install

```bash
# Core library only (graph model + parser + layout engines)
pip install .

# With PyQt6 GUI (interactive wizard)
pip install ".[gui]"

# Development (includes pytest)
pip install -e ".[dev]"
```

### Use from another project (e.g. pictosync)

```bash
cd /path/to/pictosync
pip install -e /path/to/GraphvizPy
```

```python
from gvpy.core import Graph, Node, Edge
from gvpy.engines.dot import DotLayout
from gvpy.render import render_svg
```

### Run the CLI

```bash
# Layout a DOT file → SVG
python gvcli.py input.gv -Tsvg -o output.svg

# Use a specific layout engine
python gvcli.py -Kcirco input.gv -Tsvg -o output.svg

# Launch the interactive wizard
python gvcli.py --ui

# Run all tests
python -m pytest tests/
```

## CLI Reference (`gvcli.py`)

`gvcli.py` is the unified command-line interface for all layout engines. It is the equivalent of running `dot`, `neato`, `circo`, etc. from Graphviz — one binary, multiple engines selected with `-K`.

`dot.py` is a thin wrapper that calls `gvcli.py` with `-Kdot` as the default engine. It exists for backward compatibility.

### Usage

```
python gvcli.py [options] [FILE ...]
```

### All CLI Flags

| Flag | Description |
|------|-------------|
| `-K ENGINE` | Layout engine: `dot`, `circo`, `neato`, `fdp`, `sfdp`, `twopi`, `osage`, `patchwork` |
| `-T FORMAT` | Output format: `json` (default), `svg`, `dot`, `json0`, `gxl` |
| `-o FILE` | Write output to file |
| `-O` | Auto-name output file: `input.svg`, `input.json`, etc. |
| `-G name=val` | Set graph attribute (e.g. `-Grankdir=LR`) |
| `-N name=val` | Set default node attribute (e.g. `-Nshape=box`) |
| `-E name=val` | Set default edge attribute (e.g. `-Ecolor=red`) |
| `-n` | No layout — just convert format (use existing `pos` attributes) |
| `-s SCALE` | Scale all output coordinates |
| `-y` | Invert Y axis |
| `-v` | Verbose — print summary to stderr |
| `--ui` | Launch interactive GUI wizard |
| `--list-engines` | List available layout engines and exit |

### Examples

```bash
# Default: dot engine, JSON output
python gvcli.py input.gv

# SVG output with dot engine
python gvcli.py input.gv -Tsvg -o output.svg

# Circular layout
python gvcli.py -Kcirco network.gv -Tsvg -o network.svg

# Auto-name output (input.gv → input.svg)
python gvcli.py input.gv -Tsvg -O

# DOT output with embedded layout coordinates
python gvcli.py input.gv -Tdot

# Structural JSON (no layout)
python gvcli.py input.gv -Tjson0

# Read from stdin
echo "digraph G { a -> b -> c; }" | python gvcli.py - -Tsvg

# Convert between formats (no layout needed)
python gvcli.py -n input.gv -Tgxl -o output.gxl
python gvcli.py input.json -Tdot
python gvcli.py input.gxl -Tsvg

# Override attributes
python gvcli.py input.gv -Grankdir=LR -Nshape=box -Ecolor=red -Tsvg

# Scale and invert
python gvcli.py input.gv -Tsvg -s 2.0 -y

# Launch wizard with circo engine
python gvcli.py --ui -Kcirco

# List engines
python gvcli.py --list-engines
```

**Expected output of `--list-engines`:**
```
Available layout engines:
  circo        — implemented
  dot          — implemented
  fdp          — stub
  mingle       — stub
  neato        — stub
  osage        — stub
  patchwork    — stub
  sfdp         — stub
  twopi        — stub
```

### Input Format Auto-Detection

Input format is detected by file extension:

| Extension | Format |
|-----------|--------|
| `.gv`, `.dot` | DOT language |
| `.json` | Graphviz JSON |
| `.gxl`, `.xml` | GXL (Graph eXchange Language) |
| `-` (stdin) | Auto-detected by content |

### Pipeline

```
                        ┌─── -Tdot  ──→ DOT text
                        ├─── -Tjson0 ─→ JSON (structural)
Input ──> Parse ──> ─┬──┤─── -Tgxl  ──→ GXL XML
  ↑                  │  │                              (no layout needed)
 .gv  .json  .gxl    │  └────────────────────────────────────────────
 stdin               │
                     └──> Layout (-K engine) ──> Post-process ──> Render
                              ↑                      ↑              ↑
                           dot (impl.)           write-back      -Tsvg → SVG
                           circo (impl.)         scale (-s)      -Tjson → JSON
                           neato (future)        invert (-y)     -Tdot → DOT+pos
                           ...                   pack components
```

After layout, `pos`, `width`, `height` are written back to graph attributes, and `-Tdot` produces DOT with embedded coordinates:

```bash
$ echo "digraph G { a -> b; }" | python gvcli.py - -Tdot
digraph G {
    bb="-27.0,-18.0,27.0,90.0";
    a [pos="0.0,0.0", width=0.75, height=0.5];
    b [pos="0.0,72.0", width=0.75, height=0.5];
    a -> b [pos="s,0.0,18.0 0.0,30.0 0.0,42.0 e,0.0,54.0"];
}
```

## Layout Engines

### dot — Hierarchical Layout (`gvpy.engines.dot`)

**Status:** Implemented

The Sugiyama hierarchical layout algorithm in five phases:

1. **Rank assignment** — Network simplex assigns nodes to layers
2. **Crossing minimization** — Weighted-median heuristic with transposition
3. **Coordinate assignment** — Network simplex X-positioning
4. **Edge routing** — Polyline, Bezier, orthogonal, flat edge arcs
5. **Label placement** — Collision-aware 9-position grid search

**Dot Attributes:**

| Attribute | Scope | Default | Description |
|-----------|-------|---------|-------------|
| `rankdir` | Graph | `TB` | Rank direction: `TB`, `BT`, `LR`, `RL` |
| `ranksep` | Graph | `0.5` | Separation between ranks (inches) |
| `nodesep` | Graph | `0.25` | Separation between nodes in same rank (inches) |
| `splines` | Graph | `curved` | Edge routing: `curved`, `ortho`, `polyline`, `line` |
| `ordering` | Graph | — | Node ordering: `out`, `in` |
| `concentrate` | Graph | `false` | Merge parallel edges |
| `compound` | Graph | `false` | Allow edges between clusters |
| `newrank` | Graph | `false` | Alternative ranking algorithm |
| `clusterrank` | Graph | `local` | Cluster ranking: `local`, `global`, `none` |
| `rank` | Subgraph | — | Rank constraint: `same`, `min`, `max`, `source`, `sink` |
| `ratio` | Graph | — | Aspect ratio: `compress`, `fill`, `auto`, or numeric |
| `size` | Graph | — | Maximum drawing size (inches): `"w,h"` |
| `normalize` | Graph | `false` | Normalize coordinates |
| `center` | Graph | `false` | Center drawing |
| `pack` | Graph | `true` | Pack disconnected components |
| `label` | All | — | Label text |
| `xlabel` | Node | — | External label (collision-aware placement) |
| `headlabel` | Edge | — | Label at head endpoint |
| `taillabel` | Edge | — | Label at tail endpoint |
| `labelloc` | Graph | `b` | Graph label position: `t` (top), `b` (bottom) |
| `labeljust` | Graph | `c` | Graph label justification: `l`, `c`, `r` |
| `shape` | Node | `ellipse` | Node shape (15+ shapes supported) |
| `color` | All | `black` | Outline/stroke color |
| `fillcolor` | Node | — | Fill color |
| `style` | All | — | Style: `filled`, `dashed`, `dotted`, `bold`, `invis` |
| `fontname` | All | `sans-serif` | Font family |
| `fontsize` | All | `14` | Font size (points) |
| `fontcolor` | All | `black` | Text color |
| `penwidth` | All | `1` | Line width |
| `arrowhead` | Edge | `normal` | Head arrow type (12 types) |
| `arrowtail` | Edge | `normal` | Tail arrow type |
| `dir` | Edge | `forward` | Arrow direction: `forward`, `back`, `both`, `none` |
| `weight` | Edge | `1` | Edge weight (affects ranking) |
| `minlen` | Edge | `1` | Minimum edge length in ranks |
| `constraint` | Edge | `true` | Whether edge affects ranking |
| `group` | Node | — | Node grouping for alignment |
| `pos` | Node | — | Fixed position: `"x,y"` or `"x,y!"` (pinned) |
| `pin` | Node | `false` | Pin node at `pos` |
| `fixedsize` | Node | `false` | Use exact width/height |
| `samehead` | Edge | — | Merge head endpoints |
| `sametail` | Edge | — | Merge tail endpoints |
| `headport` | Edge | — | Port on head node |
| `tailport` | Edge | — | Port on tail node |
| `lhead` | Edge | — | Logical head cluster (compound edges) |
| `ltail` | Edge | — | Logical tail cluster (compound edges) |
| `tooltip` | All | — | Hover tooltip text |
| `URL` | All | — | Clickable URL |

### circo — Circular Layout (`gvpy.engines.circo`)

**Status:** Implemented

Biconnected component decomposition with circular node placement.

**Algorithm:**
1. Biconnected decomposition (Tarjan's algorithm)
2. Block-cutpoint tree construction
3. Node ordering per block (longest path + crossing reduction)
4. Circular placement with computed radius
5. Recursive block positioning
6. Component packing

**Circo Attributes:**

| Attribute | Scope | Default | Description |
|-----------|-------|---------|-------------|
| `mindist` | Graph | `1.0` | Minimum distance between adjacent nodes (inches) |
| `root` | Graph | (first node) | Root node for DFS — affects block tree orientation |
| `oneblock` | Graph | `false` | Skip biconnected decomposition |

### Stub Engines (not yet implemented)

| Engine | Description | C Reference |
|--------|-------------|-------------|
| `neato` | Spring-model force-directed (stress majorization) | `lib/neatogen/` |
| `fdp` | Force-directed placement (Fruchterman-Reingold) | `lib/fdpgen/` |
| `sfdp` | Scalable force-directed (multi-level + Barnes-Hut) | `lib/sfdpgen/` |
| `twopi` | Radial layout (BFS concentric rings) | `lib/twopigen/` |
| `osage` | Recursive cluster packing | `lib/osage/` |
| `patchwork` | Treemap visualization | `lib/patchwork/` |
| `mingle` | Edge bundling (post-processor) | `lib/mingle/` |

## Supported Formats

| Format | Read | Write | Extension | Description |
|--------|------|-------|-----------|-------------|
| **DOT** | Yes | Yes | `.gv`, `.dot` | Graphviz DOT language (ANTLR4 parser) |
| **JSON** | Yes | Yes | `.json` | Graphviz-compatible JSON with layout coords |
| **JSON0** | Yes | Yes | `.json` | Graphviz-compatible JSON (structural only) |
| **GXL** | Yes | Yes | `.gxl` | Graph eXchange Language (XML-based) |
| **SVG** | — | Yes | `.svg` | Scalable Vector Graphics (rendered output) |

### Python API

```python
# DOT read/write (gvpy.grammar)
from gvpy.grammar import read_gv, read_gv_file, write_gv, write_gv_file

# SVG, JSON, GXL (gvpy.render)
from gvpy.render import render_svg, read_json, write_json0, read_gxl, write_gxl

# Layout engines (gvpy.engines)
from gvpy.engines.dot import DotLayout
from gvpy.engines.circo import CircoLayout
from gvpy.engines import get_engine

# Full pipeline
graph = read_gv('digraph G { a -> b -> c; }')
result = DotLayout(graph).layout()
svg = render_svg(result)
```

## Project Structure

```
GraphvizPy/
├── gvcli.py                      # Unified CLI (all engines, all formats)
├── dot.py                        # Wrapper: calls gvcli.py with -Kdot default
├── pyproject.toml                # Package definition (pip install -e .)
│
├── gvpy/                         # Main Python package
│   │
│   ├── core/                     # Graph data structures (port of Graphviz cgraph)
│   │   ├── graph.py              #   Graph class with mixin architecture
│   │   ├── node.py               #   Node and CompoundNode
│   │   ├── edge.py               #   Edge with half-edge pairs
│   │   ├── headers.py            #   Agclos, Agdesc, AgIdDisc, callbacks
│   │   ├── defines.py            #   ObjectType, EdgeType, GraphEvent enums
│   │   ├── agobj.py              #   Base class for graph objects
│   │   ├── error.py              #   Logging and error handling
│   │   └── _graph_*.py           #   Mixin modules (nodes, edges, subgraphs, etc.)
│   │
│   ├── grammar/                  # ANTLR4 grammar and DOT language I/O
│   │   ├── GVLexer.g4            #   Lexer grammar
│   │   ├── GVParser.g4           #   Parser grammar
│   │   ├── gv_reader.py          #   read_gv(), read_gv_file()
│   │   ├── gv_writer.py          #   write_gv(), write_gv_file()
│   │   ├── gv_visitor.py         #   ANTLR4 parse tree → Graph objects
│   │   ├── build_grammar.bat     #   ANTLR4 regeneration script
│   │   └── generated/            #   Auto-generated GVLexer.py, GVParser.py
│   │
│   ├── engines/                  # Layout engines
│   │   ├── __init__.py           #   Engine registry: get_engine(), list_engines()
│   │   ├── base.py               #   Abstract LayoutEngine base class
│   │   ├── wizard.py             #   Interactive PyQt6 layout wizard (any engine)
│   │   ├── dot/                  #   Hierarchical layout (Sugiyama)
│   │   │   └── dot_layout.py
│   │   ├── circo/                #   Circular layout (biconnected decomposition)
│   │   │   └── circo_layout.py
│   │   ├── neato/                #   Spring-model (stub)
│   │   ├── fdp/                  #   Force-directed (stub)
│   │   ├── sfdp/                 #   Scalable force-directed (stub)
│   │   ├── twopi/                #   Radial (stub)
│   │   ├── osage/                #   Cluster packing (stub)
│   │   ├── patchwork/            #   Treemap (stub)
│   │   └── mingle/               #   Edge bundling (stub)
│   │
│   └── render/                   # Output rendering and format I/O
│       ├── svg_renderer.py       #   Layout dict → SVG
│       ├── json_io.py            #   Graphviz JSON/JSON0 read/write
│       └── gxl_io.py             #   GXL (XML) read/write
│
├── test_data/                    # Test files (.gv, .dot, .json, .gxl)
│
├── tests/                        # pytest test suite (558 tests)
│   ├── test_cgraph_api.py        #   Core API (76 tests)
│   ├── test_node_operations.py   #   Node CRUD (31 tests)
│   ├── test_edge_operations.py   #   Edge CRUD (14 tests)
│   ├── test_subgraph_operations.py #  Subgraph CRUD (12 tests)
│   ├── test_callbacks.py         #   Callback system (20 tests)
│   ├── test_graph_core.py        #   Graph init, attrs, algorithms (35 tests)
│   ├── test_compound_nodes.py    #   Compound nodes (8 tests)
│   ├── test_dot_parser.py        #   DOT parser (44 tests)
│   ├── test_dot_layout.py        #   Dot layout + attributes (165+ tests)
│   ├── test_svg_renderer.py      #   SVG rendering (18 tests)
│   ├── test_formats.py           #   Format roundtrip (71 tests)
│   └── test_circo_layout.py      #   Circo layout (25 tests)
│
└── lib/                          # Original C-to-Python translation (reference)
```

## Interactive Wizard

Launch with `python gvcli.py --ui` for a three-pane GUI:

- **Left**: DOT source editor
- **Center**: Live SVG preview (aspect-preserving)
- **Right**: Parameter controls with engine selector, graph/node/edge attributes
- **Bottom**: Command line display with Run button (Ctrl+Enter)

The engine selector dropdown lets you switch between layout engines at runtime.

```bash
python gvcli.py --ui                  # default: dot engine
python gvcli.py --ui -Kcirco         # start with circo engine
python gvcli.py --ui input.gv        # load a file
```

## Dependencies

- Python 3.13+

Core (installed with `pip install .`):
- antlr4-python3-runtime ~4.13.0
- numpy ~2.2.1
- scipy ~1.14.1

GUI extra (installed with `pip install ".[gui]"`):
- PyQt6 ~6.7.0
- pyqtgraph

See `pyproject.toml` for the full dependency specification.

## Test Coverage

| Component | Tests | Status |
|---|---|---|
| DOT parser | 44 | All pass |
| Dot layout + labels | 165+ | All pass |
| Circo layout | 25 | All pass |
| SVG renderer | 18 | All pass |
| Core API | 100+ | All pass |
| Format I/O (DOT/JSON/GXL) | 71 | All pass |
| Attribute coverage | 101/101 | All tested |
| **Total** | **558** | **All pass** |

## Original Code

The original Graphviz C source is from https://gitlab.com/graphviz/graphviz/

The `lib/` directory contains a literal C-to-Python translation for reference. The `gvpy/` package is the active, refactored implementation.

## Related Projects

- [pictosync](https://github.com/pjm4github/pictosync) — rendering pipeline via `attribute_schema.json`
