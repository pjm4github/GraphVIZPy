# GraphvizPy

A pure-Python implementation of the Graphviz graph visualization toolkit, featuring an ANTLR4-based DOT language parser, a hierarchical layout engine (dot), and an interactive PyQt6 GUI.

## Purpose

- Port the Graphviz C codebase to Python 3.13+ for exploration and modernization
- Replace C data structures with Python dicts, sets, and typing constructs
- Provide an interactive GUI for graph editing and layout visualization
- Integrate with the [pictosync](https://github.com/pjm4github/pictosync) project for rendering

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Layout a DOT file and output JSON coordinates
python dot.py test_data/example1.gv

# Layout and render as SVG
python dot.py test_data/example1.gv -Tsvg -o example1.svg

# Launch the interactive wizard
python dot.py --ui

# Run all tests
python -m pytest tests/
```

## Project Structure

```
GraphvizPy/
├── dot.py                    # CLI entry point (equivalent of Graphviz dot command)
├── MainGraphvisPy.py         # Interactive PyQt6 graph editor (v1.7.12)
├── settings.py               # PyQt6 UI settings
├── requirements.txt          # Python dependencies
│
├── pycode/                   # Core Python library (mirrors Graphviz lib/ structure)
│   ├── cgraph/               # Core graph library (port of Graphviz cgraph)
│   │   ├── graph.py        # Graph class: nodes, edges, subgraphs, callbacks
│   │   ├── node.py         # Node and CompoundNode classes
│   │   ├── edge.py         # Edge class with half-edge pairs
│   │   ├── headers.py        # Type definitions, callback system, ID discipline
│   │   ├── defines.py        # Constants (ObjectType, EdgeType, GraphEvent)
│   │   ├── agobj.py          # Base class for all graph objects
│   │   ├── error.py        # Logging and error handling
│   │   └── graph_print.py    # ASCII tree printer for debugging
│   │
│   ├── dot/                  # DOT parser + hierarchical layout engine
│   │   ├── dot_reader.py     # Public API: read_dot(), read_dot_file()
│   │   ├── dot_visitor.py    # ANTLR4 parse tree visitor → Graph objects
│   │   ├── dot_layout.py     # 4-phase hierarchical layout algorithm
│   │   ├── svg_renderer.py   # SVG output renderer
│   │   ├── dot_wizard.py     # Interactive PyQt6 layout wizard
│   │   ├── DOTLexer.g4       # ANTLR4 lexer grammar
│   │   ├── DOTParser.g4      # ANTLR4 parser grammar
│   │   ├── build_grammar.bat # ANTLR4 regeneration script
│   │   └── generated/        # Auto-generated lexer, parser, visitor
│   │
│   ├── circo/                # Circular layout engine (future)
│   ├── fdp/                  # Force-directed layout (future)
│   ├── neato/                # Spring-model layout (future)
│   ├── sfdp/                 # Multiscale force-directed (future)
│   └── twopi/                # Radial layout (future)
│
├── lib/                      # Original C-to-Python translation (reference only)
│
├── test_data/                # DOT test files (127 files from Graphviz test suite)
│   ├── example1.gv           # Simple undirected graph
│   ├── world.gv              # Complex directed graph with rank constraints
│   └── *.dot                 # Graphviz test cases
│
└── tests/                    # Test suite (pytest)
    ├── test_dot_parser.py    # DOT parser tests (44 tests)
    ├── test_dot_layout.py    # Layout engine tests (150+ tests)
    ├── test_svg_renderer.py  # SVG renderer tests (18 tests)
    └── test_*.py             # Graph library tests (100+ tests)
```

## DOT Parser

The DOT parser uses ANTLR4 to parse the [DOT language](https://graphviz.org/doc/info/lang.html) into Graph objects. It supports the full DOT syntax:

- Directed (`digraph`) and undirected (`graph`) graphs
- Strict mode (no duplicate edges)
- Node and edge attribute lists (`[key=value, ...]`)
- Default attribute statements (`node [shape=box]; edge [style=dashed]`)
- Subgraphs and clusters (`subgraph cluster_0 { ... }`)
- Edge chains (`A -> B -> C`)
- Ports (`a:port:compass`)
- All identifier types: bare, numeric, quoted strings, HTML labels (`<...>`)
- Comments: `//`, `/* */`, `#` preprocessor
- Multi-graph files (multiple graph blocks in one file)
- UTF-8 and latin-1 encoding

### Parser Usage

```python
from pycode.dot import read_dot, read_dot_file

# Parse from string
graph = read_dot('digraph G { a -> b -> c; }')

# Parse from file
graph = read_dot_file("input.gv")

# Parse file with multiple graphs
graphs = read_dot_all("digraph A { x; } digraph B { y; }")
```

## Dot Layout Engine

The layout engine (`pycode/dot_layout.py`) implements the Sugiyama hierarchical layout algorithm in four phases:

1. **Rank assignment** — Network simplex assigns nodes to hierarchical layers. Cycle breaking via DFS. Supports `rank=same/min/max`, `newrank`, cluster-aware ranking.

2. **Crossing minimization** — Iterative weighted-median heuristic with transposition. Configurable via `mclimit` and `remincross`.

3. **Coordinate assignment** — Y from rank spacing, X via network simplex balancing. Supports `rankdir` (TB/BT/LR/RL), `size`, `ratio`, `quantum`, `normalize`.

4. **Edge routing** — Polyline through virtual nodes, Catmull-Rom → Bézier conversion, orthogonal routing. Supports ports, compound edges (`lhead`/`ltail`), `samehead`/`sametail`.

### Layout Usage

```python
from pycode.dot import read_dot_file
from pycode.dot.dot_layout import DotLayout
from pycode.dot.svg_renderer import render_svg

# Parse and layout
graph = read_dot_file("input.gv")
result = DotLayout(graph).layout()  # Returns JSON-serializable dict

# Render to SVG
svg_text = render_svg(result)
```

### Layout JSON Output

```json
{
  "graph": {"name": "G", "directed": true, "bb": [0, 0, 200, 150]},
  "nodes": [{"name": "a", "x": 100, "y": 50, "width": 54, "height": 36}],
  "edges": [{"tail": "a", "head": "b", "points": [[100, 68], [100, 114]]}],
  "clusters": [{"name": "cluster_0", "bb": [10, 10, 190, 140], "nodes": ["a"]}]
}
```

### Supported Attributes

The layout engine recognizes 100+ Graphviz attributes including:
`rankdir`, `ranksep`, `nodesep`, `splines`, `shape`, `label`, `color`, `fillcolor`, `fontname`, `fontsize`, `style`, `penwidth`, `arrowhead`, `arrowtail`, `dir`, `constraint`, `minlen`, `weight`, `group`, `compound`, `concentrate`, `ordering`, `clusterrank`, `newrank`, `pos`, `pin`, `fixedsize`, `headport`, `tailport`, `headclip`, `tailclip`, `samehead`, `sametail`, `xlabel`, `headlabel`, `taillabel`, `tooltip`, `URL`, and more.

See `dot_layout.py` module docstring for the complete attribute reference.

## Graph, Node, and Edge Classes

### Graph (`pycode/cgraph/graph.py`)

The `Graph` class is the central data structure, representing a directed or undirected graph with support for subgraphs, compound nodes, and an event callback system.

```python
from pycode.cgraph.graph import Graph

g = Graph(name="MyGraph", directed=True, strict=False)
g.method_init()

# Add nodes and edges
node_a = g.add_node("A")
node_b = g.add_node("B")
edge = g.add_edge("A", "B", edge_name="e1")

# Subgraphs
sub = g.add_subgraph("cluster_0")
sub.add_node("C")

# Attributes
g.set_graph_attr("rankdir", "LR")
node_a.agset("shape", "box")
edge.agset("label", "connects")
```

### Node (`pycode/cgraph/node.py`)

Nodes support compound node operations (containing subgraphs), centrality metrics, and edge splicing.

```python
node = g.add_node("A")
node.agset("label", "Component A")
node.agset("shape", "box")

# Access edges
for edge in node.outedges:
    print(f"{node.name} -> {edge.head.name}")

# Compound nodes
node.make_compound("sub_cluster")
```

### Edge (`pycode/cgraph/edge.py`)

Edges use a half-edge model (each logical edge has an out-edge and an in-edge) for efficient traversal.

```python
edge = g.add_edge("A", "B")
edge.agset("label", "calls")
edge.agset("color", "red")

print(edge.tail.name)  # "A"
print(edge.head.name)  # "B"
```

## CLI Reference

```
python dot.py --help

Usage: dot.py [--ui] [-T FORMAT] [-o FILE] [-G name=value]
              [-N name=value] [-E name=value] [-v] [FILE ...]

Options:
  --ui           Launch interactive GUI wizard
  -T FORMAT      Output format: json (default) or svg
  -o FILE        Write output to file
  -G name=value  Set graph attribute (e.g. -Grankdir=LR)
  -N name=value  Set default node attribute (e.g. -Nshape=box)
  -E name=value  Set default edge attribute (e.g. -Ecolor=red)
  -v, --verbose  Print layout summary to stderr
```

## Interactive Wizard

Launch with `python dot.py --ui` for a three-pane GUI:
- **Left**: DOT source editor with syntax highlighting
- **Center**: Live SVG preview (aspect-preserving)
- **Right**: Parameter controls for graph, node, and edge attributes
- **Bottom**: Command line display with Run button (Ctrl+Enter)

## Dependencies

- Python 3.13+
- PyQt6 ~6.7.0
- antlr4-python3-runtime ~4.13.0
- numpy, scipy, scikit-image, scanf, fputs

## Original Code

The original Graphviz C source is from https://gitlab.com/graphviz/graphviz/

Local clone: `C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz`

The `lib/` directory contains a literal C-to-Python translation for reference. The `pycode/` directory is the active, refactored implementation.

## Test Coverage

| Component | Tests | Status |
|---|---|---|
| DOT parser | 44 | All pass |
| Layout engine | 150+ | All pass |
| SVG renderer | 18 | All pass |
| Graph library | 100+ | 23 pre-existing failures (hide/expose) |
| Test file validation | 122/128 | 6 parse errors (malformed content) |
| Attribute coverage | 101/101 | All tested |

## Related Projects

- [pictosync](https://github.com/pjm4github/pictosync) — rendering pipeline via `attribute_schema.json`
