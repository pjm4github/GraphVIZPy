# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

GraphvizPy is a pure Python port of the C-based Graphviz library, enhanced with an
interactive PyQt6 GUI for graph editing and layout. It targets Python 3.13+ and replaces
C data structures with Python dicts, sets, and typing module constructs.

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
- The DOT parser uses an ANTLR4 grammar (GVLexer.py + GVParser.py in gvpy/grammar/generated/)
- Rendering is delegated to pictosync via attribute_schema.json
- The layout tools will work with both code bases

## Active TODO File

- **`TODO.md`** — consolidated roadmap. Python ↔ C divergence table (§1),
  dot-engine priority work (§2), splines port completion status (§3), core
  refactor (§4), other layout engines (§5), MainGraphvisPy GUI (§6),
  pictosync merge (§7), diagnostics + tooling (§8). Always check this
  before starting new work.

The legacy per-topic files (`TODO_dot_layout.md`, `TODO_dot_splines_port.md`,
`TODO_layout_engines.md`, `TODO_main_gui.md`, `TODO_pictosync_merge.md`,
`TODO_core_refactor.md`) are kept for archival history only and are not
maintained.

## Reference C Implementation
The authoritative Graphviz C source used for behavioral matching is located at:
`C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz`

### Key C source files for dot layout:
- `lib/dotgen/` — main dot layout engine (rank.c, position.c, edge.c, dotinit.c)
- `lib/common/` — shared graph routines
- `cmd/dot/` — dot CLI entry point
- `lib/cgraph/` — cgraph data model (reference for gvpy/core/)

### Build system (CRITICAL — read carefully)
CLion manages the CMake configuration using its bundled MinGW toolchain.
The `cmake-build-debug-mingw` directory and its `CMakeCache.txt` were generated
by CLion and must not be reconfigured.

**Compiler paths (verified from CMakeCache.txt):**
- **C Compiler:** `C:\Program Files\JetBrains\CLion 2023.2.2\bin\mingw\bin\gcc.exe`
- **cmake:** `C:\Program Files\JetBrains\CLion 2023.2.2\bin\cmake\win\x64\bin\cmake.exe`
- **ninja:** detected automatically from CLion MinGW toolchain

**Two MinGW installations exist on this machine — they are NOT interchangeable:**
- ✅ CLion bundled MinGW (correct): `C:\Program Files\JetBrains\CLion 2023.2.2\bin\mingw\bin\`
- ❌ MSYS2 MinGW (wrong): `C:\msys64\mingw64\bin\`

**Rules:**
1. NEVER invoke `cc.exe`, `gcc.exe`, or any compiler directly
2. NEVER run `cmake -B` or reconfigure — this will overwrite CLion's cache
3. NEVER use cmake or ninja from PATH — always use the full CLion cmake path
4. ALWAYS use the exact build command below — no variations

**The only correct build command:**

```powershell
$env:PATH = "C:\Program Files\JetBrains\CLion 2023.2.2\bin\mingw\bin;" + $env:PATH
& "C:\Program Files\JetBrains\CLion 2023.2.2\bin\cmake\win\x64\bin\cmake.exe" `
    --build "C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\cmake-build-debug-mingw" `
    --target dot
```

If the build fails, STOP and report the exact error. Do NOT attempt to switch
compilers or find alternative build paths.

### Reference binary (authoritative dot.exe):
`C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\cmake-build-debug-mingw\cmd\dot\dot.exe`

Always use this exact path. Never use any `dot.exe` found on PATH — it may be
a different version and will produce non-comparable output.

Verify the binary works before running traces:

```powershell
& "C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\cmake-build-debug-mingw\cmd\dot\dot.exe" -V
```

## Instrumentation Workflow

The primary active task is making `gvpy/engines/dot/dot_layout.py` produce output
that matches `dot.exe` step-for-step. Existing trace output files are already present
in the repo root (`trace_reference.txt`, `trace_python.txt`) — check these before
generating new ones to avoid redundant builds.

The workflow is:

1. **Check `TODO.md`** (§1 divergences + §2 priority items) for the current
   target before starting.

2. **Read the corresponding C source** in
   `C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\lib\dotgen\`
   to understand the algorithm before modifying anything.

3. **Instrument the C source** — add trace statements to the relevant `.c` file:

```c
fprintf(stderr, "[TRACE rank] node=%s rank=%d\n", agnameof(n), rank);
```

4. **Build the instrumented dot.exe** using ONLY the command in the Build System
   section above. Verify with `-V` that the binary updated (check timestamp).

5. **Capture the C reference trace:**

```powershell
$DOT = "C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\cmake-build-debug-mingw\cmd\dot\dot.exe"
& $DOT -Tsvg test_data\example1.gv 2> trace_reference.txt
```

6. **Run the Python equivalent and capture its trace:**

```powershell
.venv\Scripts\python.exe dot.py test_data\example1.gv -Tsvg -o output_py.svg 2> trace_python.txt
```

7. **Diff the two trace files:**

```powershell
.venv\Scripts\python.exe tools\compare_traces.py trace_reference.txt trace_python.txt
```

8. **Fix `gvpy/engines/dot/dot_layout.py`** to match the C behavior at the divergence point.

9. **Update `TODO.md`** — mark the divergence resolved (§1) or update the
   priority entry (§2) to reflect what was completed and what is next.

10. **Repeat** for the next phase.

### Trace convention in Python
Add trace output using:

```python
import sys
print(f"[TRACE rank] node={node.name} rank={rank}", file=sys.stderr)
```

Use identical `[TRACE <phase>]` prefix tags in both C and Python so diffs are
line-comparable. Canonical phase tags:

| Tag       | C source file              | Python location                                          |
|-----------|----------------------------|----------------------------------------------------------|
| `rank`    | `lib/dotgen/rank.c`        | `gvpy/engines/dot/dot_layout.py` rank assignment         |
| `order`   | `lib/dotgen/order.c`       | `gvpy/engines/dot/dot_layout.py` ordering phase          |
| `position`| `lib/dotgen/position.c`    | `gvpy/engines/dot/dot_layout.py` coordinate assignment   |
| `spline`  | `lib/dotgen/splines.c`     | `gvpy/engines/dot/dot_layout.py` edge routing            |
| `label`   | `lib/dotgen/labeldce.c`    | `gvpy/engines/dot/dot_layout.py` label placement         |

## Commands

```powershell
# Install dependencies
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Run the dot layout engine
.venv\Scripts\python.exe dot.py test_data/example1.gv -Tsvg -o output.svg

# Run the graphviz CLI wrapper
.venv\Scripts\python.exe gvcli.py -Tsvg test_data/example1.gv -o output.svg

# Launch the interactive PyQt6 editor
.venv\Scripts\python.exe MainGraphvisPy.py

# Run all tests
.venv\Scripts\python.exe -m pytest tests/ -x -q --ignore=tests/test_all_files.py

# Run a single test file
.venv\Scripts\python.exe -m pytest tests/test_dot_layout.py

# Build instrumented dot.exe
$env:PATH = "C:\Program Files\JetBrains\CLion 2023.2.2\bin\mingw\bin;" + $env:PATH
& "C:\Program Files\JetBrains\CLion 2023.2.2\bin\cmake\win\x64\bin\cmake.exe" --build "C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\cmake-build-debug-mingw" --target dot

# Capture C reference trace
$DOT = "C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz\cmake-build-debug-mingw\cmd\dot\dot.exe"
& $DOT -Tsvg test_data\example1.gv 2> trace_reference.txt

# Capture Python trace
.venv\Scripts\python.exe dot.py test_data\example1.gv -Tsvg -o output_py.svg 2> trace_python.txt

# Diff traces
.venv\Scripts\python.exe tools\compare_traces.py trace_reference.txt trace_python.txt
```

## Architecture

### Top-level files
- **`dot.py`** — CLI entry point (equivalent of Graphviz `dot` command)
- **`gvcli.py`** — Graphviz CLI wrapper
- **`gvtools.py`** — Utility tools
- **`MainGraphvisPy.py`** — Interactive PyQt6 graph editor
- **`settings.py`** — Application settings
- **`GVP_settings.json`** — Persistent application settings (JSON)
- **`pyproject.toml`** — Project metadata and build config
- **`pytest.ini`** — Pytest configuration
- **`Docs/`** — Project documentation
- **`test_data/`** — DOT input files for testing and trace generation
- **`tests/`** — Pytest test suite

### Package Structure (`gvpy/`)

```
gvpy/
├── core/                      # Core graph data model (port of Graphviz cgraph)
│   ├── graph.py               # Graph class: nodes, edges, subgraphs, callbacks
│   ├── node.py                # Node class
│   ├── edge.py                # Edge class with half-edge pairs
│   ├── agobj.py               # Base class for all graph objects
│   ├── headers.py             # Type definitions, callback system, ID discipline
│   ├── defines.py             # Constants (ObjectType, EdgeType, GraphEvent)
│   ├── error.py               # Logging and error handling
│   ├── graph_print.py         # ASCII tree printer for debugging
│   ├── _graph_attrs.py        # Graph attribute management
│   ├── _graph_callbacks.py    # Graph event callbacks
│   ├── _graph_edges.py        # Edge operations
│   ├── _graph_id.py           # ID discipline
│   ├── _graph_nodes.py        # Node operations
│   └── _graph_subgraphs.py    # Subgraph operations
│
├── engines/                   # Layout engines
│   ├── base.py                # Abstract base layout engine
│   ├── layout_features.py     # Shared layout utilities
│   ├── wizard.py              # Interactive PyQt6 layout wizard
│   ├── dot/
│   │   └── dot_layout.py      # Hierarchical layout  <- PRIMARY INSTRUMENTATION TARGET
│   ├── circo/
│   │   └── circo_layout.py    # Circular layout
│   ├── fdp/
│   │   └── fdp_layout.py      # Force-directed layout
│   ├── neato/
│   │   └── neato_layout.py    # Spring-model layout
│   ├── osage/
│   │   └── osage_layout.py    # Osage layout
│   ├── patchwork/
│   │   └── patchwork_layout.py
│   ├── sfdp/
│   │   └── sfdp_layout.py     # Multiscale force-directed
│   └── twopi/
│       └── twopi_layout.py    # Radial layout
│
├── grammar/                   # DOT language parser
│   ├── gv_reader.py           # Public API: read_dot(), read_dot_file()
│   ├── gv_visitor.py          # ANTLR4 parse tree visitor
│   ├── gv_writer.py           # DOT language writer
│   └── generated/             # Auto-generated ANTLR4 parser files
│       ├── GVLexer.py
│       ├── GVParser.py
│       └── GVParserVisitor.py
│
├── render/                    # Output renderers
│   ├── svg_renderer.py        # SVG output
│   ├── png_renderer.py        # PNG output
│   ├── json_io.py             # JSON import/export
│   └── gxl_io.py              # GXL import/export
│
└── tools/                     # Graphviz utility tools (ports of C utilities)
    ├── acyclic.py
    ├── bcomps.py
    ├── ccomps.py
    └── edgepaint.py
```

### C source to Python mapping

| C library           | Python equivalent                                        |
|---------------------|----------------------------------------------------------|
| `lib/cgraph/`       | `gvpy/core/`                                             |
| `lib/dotgen/`       | `gvpy/engines/dot/dot_layout.py`                         |
| `lib/common/`       | `gvpy/engines/base.py`, `gvpy/engines/layout_features.py`|
| `cmd/dot/`          | `dot.py`                                                 |
| DOT language parser | `gvpy/grammar/`                                          |

## Key Dependencies

PyQt6 (~6.7.0), antlr4-python3-runtime (~4.13.0), numpy, scipy. Full list in `requirements.txt`.

## Naming Conventions

- Module names match original C Graphviz names where possible
- Package names match C Graphviz lib/ directory names where applicable
- Data structures use capitalized first character per PEP 8
- Types use the `typing` module; enums use `Enum`
- snake_case for all internal identifiers
