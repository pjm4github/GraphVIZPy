# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GraphvizPy is a pure Python port of the C-based Graphviz library, enhanced with an interactive PyQt6 GUI for graph editing and layout. It targets Python 3.13+ and replaces C data structures with Python dicts, sets, and typing module constructs.

## Relationship to Pictosync
This project is an adjacent module planned to merge with:
`C:\Users\pmora\OneDrive\Documents\Git\GitHub\pictosync`

### Key Pictosync conventions to follow:
- PyQt6 QGraphicsScene-based canvas architecture
- ANTLR4 grammar parsing pipeline
- SVGNodeRegistry pattern for node type management
- snake_case for internal identifiers

### Merge boundary:
- The codebase has been migrated to PyQt6
- The DOT parser uses an ANTLR4 grammar (DOTLexer.g4 + DOTParser.g4)
- Rendering is delegated to pictosync via attribute_schema.json
- The layout tools will work with both code bases

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the dot layout engine
python dot.py test_data/example1.gv -Tsvg -o output.svg

# Launch the interactive wizard
python dot.py --ui

# Run all tests
python -m pytest tests/

# Run a single test file
python -m pytest tests/test_dot_layout.py
```

## Architecture

### Package Structure (`pycode/`)

```
pycode/
├── cgraph/            # Core graph library (port of Graphviz cgraph)
│   ├── graph.py     # Graph class: nodes, edges, subgraphs, callbacks
│   ├── node.py      # Node and CompoundNode classes
│   ├── edge.py      # Edge class with half-edge pairs
│   ├── headers.py     # Type definitions, callback system, ID discipline
│   ├── defines.py     # Constants (ObjectType, EdgeType, GraphEvent)
│   ├── agobj.py       # Base class for all graph objects
│   ├── error.py     # Logging and error handling
│   └── graph_print.py # ASCII tree printer for debugging
│
├── dot/               # DOT parser + hierarchical layout engine
│   ├── dot_reader.py  # Public API: read_dot(), read_dot_file()
│   ├── dot_visitor.py # ANTLR4 parse tree visitor
│   ├── dot_layout.py  # 4-phase hierarchical layout algorithm
│   ├── svg_renderer.py# SVG output renderer
│   ├── dot_wizard.py  # Interactive PyQt6 layout wizard
│   ├── DOTLexer.g4    # ANTLR4 lexer grammar
│   ├── DOTParser.g4   # ANTLR4 parser grammar
│   └── generated/     # Auto-generated parser files
│
├── circo/             # Circular layout (future)
├── fdp/               # Force-directed layout (future)
├── neato/             # Spring-model layout (future)
├── sfdp/              # Multiscale force-directed (future)
└── twopi/             # Radial layout (future)
```

### Other Key Files

- **`dot.py`** — CLI entry point (equivalent of Graphviz `dot` command)
- **`MainGraphvisPy.py`** — Interactive PyQt6 graph editor (v1.7.12)
- **`test_data/`** — DOT test files (127 files from Graphviz test suite)
- **`lib/`** — Original literal C-to-Python translation (reference only)

## Key Dependencies

PyQt6 (~6.7.0), antlr4-python3-runtime (~4.13.0), numpy, scipy. Full list in `requirements.txt`.

## Naming Conventions

- Module names match original C Graphviz names where possible (e.g., `CGGraph`, `CGNode`)
- Package names match C Graphviz lib/ directory names (cgraph, dot, circo, fdp, etc.)
- Data structures use capitalized first character per PEP 8
- Types use the `typing` module; enums use `Enum`
