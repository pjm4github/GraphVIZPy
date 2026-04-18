# GraphvizPy

A pure-Python implementation of the Graphviz graph visualization toolkit
plus a graph-attached simulation framework.  Features an ANTLR4-based DOT
language parser, eight layout engines (dot/neato/fdp/sfdp/circo/twopi/
osage/patchwork), two simulation paradigms (SimPy-style discrete events
and PyCBD-style synchronous block diagrams), and an interactive PyQt6 GUI.

## Purpose

- **Port the Graphviz C codebase** to Python 3.13+ for exploration and
  modernization, replacing C data structures with Python dicts, sets, and
  typing constructs.
- **Unify layout and simulation** behind a single ``Graph.views[name]``
  attachment model so the same graph can be laid out *and* simulated in
  parallel without polluting the core data model.
- **Provide an interactive GUI** for graph editing, layout visualization,
  and (eventually) simulation playback.
- **Integrate with the [pictosync](https://github.com/pjm4github/pictosync)
  project** for rendering — every view supports a JSON round-trip so the
  graphical canvas and the JSON editor stay in lock-step.

## Architecture goals

The long-term direction is a **view-architecture migration** described in
``TODO_core_refactor.md``.  Every domain-specific projection of a Graph
(layout, simulation, analysis, render-state) lives behind a uniform
attachment point:

```
gvpy.core.graph_view.GraphView                        ← abstract base
├── gvpy.engines.layout.base.LayoutView               ← abstract intermediate
│   ├── DotLayout, NeatoLayout, FdpLayout, ...        ← concrete layout engines
│   └── PictoLayout (planned)                         ← pictosync renderer
└── gvpy.engines.sim.base.SimulationView              ← abstract intermediate
    ├── EventSimulationView                           ← SimPy-style discrete events
    └── CBDSimulationView                             ← PyCBD-style three-phase Mealy
```

A graph carries its views in ``graph.views[name]``, which mirrors C
Graphviz's ``Agraphinfo_t`` extension data accessed via ``AGDATA(g)``.
Each view owns its per-node / per-edge derived state and exposes it
through a uniform query API; views never write back into the underlying
``Graph`` so multiple engines can coexist:

```python
from gvpy.core.graph import Graph
from gvpy.engines.layout.dot import DotLayout
from gvpy.engines.sim import CBDSimulationView, CompoundBlock, GainBlock

g = Graph(name="g", directed=True)
# ...build the graph...

# A layout view and a simulation view, on the same graph, side by side.
g.attach_view(DotLayout(g))                # graph.views["dot"]
g.attach_view(CBDSimulationView(g))        # graph.views["sim_cbd"]
```

Every view supports a ``to_json``/``from_json`` round-trip so a paused
state (positions for layout, current iteration + block states for sim)
can be saved, restored, or exchanged with the pictosync graphical
editor.

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
# Layout (Graphviz parity)
from gvpy.core import Graph, Node, Edge
from gvpy.engines.layout.dot import DotLayout
from gvpy.render import render_svg

# Simulation (event-driven, SimPy-style)
from gvpy.engines.sim import Environment, EventSimulationView

# Simulation (synchronous block diagrams, PyCBD-style)
from gvpy.engines.sim import (
    CBDSimulationView, CompoundBlock,
    ConstantBlock, GainBlock, AdderBlock, DelayBlock,
)
```

### Run the CLI

```bash
# Layout a DOT file → SVG
python gvcli.py input.gv -Tsvg -o output.svg

# Layout a DOT file → PNG (requires Pillow)
python gvcli.py input.gv -Tpng -o output.png

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
| `-T FORMAT` | Output format: `json` (default), `svg`, `png`, `dot`, `json0`, `gxl` |
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

# PNG output (requires Pillow)
python gvcli.py input.gv -Tpng -o output.png

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
  fdp          — implemented
  neato        — implemented
  osage        — implemented
  patchwork    — implemented
  sfdp         — implemented
  twopi        — implemented
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

### dot — Hierarchical Layout (`gvpy.engines.layout.dot`)

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

### circo — Circular Layout (`gvpy.engines.layout.circo`)

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

### neato — Spring-Model Layout (`gvpy.engines.layout.neato`)

Stress majorization, Kamada-Kawai, or SGD to minimize stress energy from graph-theoretic distances. Best for undirected graphs up to ~1000 nodes.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `mode` | `major` | Algorithm: `major` (stress majorization), `KK`, `sgd` |
| `model` | `shortpath` | Distance model: `shortpath`, `circuit`, `subset` |
| `Damping` | `0.99` | KK velocity damping |
| `epsilon` | `0.0001*\|V\|` | Convergence threshold |
| `len` (edge) | `1.0` | Desired edge length (inches) |

### fdp — Force-Directed Placement (`gvpy.engines.layout.fdp`)

Fruchterman-Reingold spring-electrical model with grid-accelerated repulsive forces and linear cooling. Two-phase: layout + overlap removal.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `K` | `0.3` | Spring constant / ideal edge length |
| `maxiter` | `600` | Maximum iterations |
| `len` (edge) | K | Desired edge length |
| `weight` (edge) | `1` | Spring strength multiplier |

### sfdp — Scalable Force-Directed (`gvpy.engines.layout.sfdp`)

Extends fdp with multilevel coarsening and Barnes-Hut quadtree for O(n log n) repulsive forces. Handles 10K+ nodes.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `K` | auto | Spring constant |
| `repulsiveforce` | `1` | Repulsive exponent |
| `levels` | unlimited | Max coarsening levels |
| `smoothing` | `none` | Post-process: `spring`, `avg_dist`, etc. |
| `quadtree` | `normal` | Barnes-Hut mode: `normal`, `fast`, `none` |
| `beautify` | `false` | Arrange leaves in circle around root |
| `rotation` | `0` | Rotate final layout (degrees) |

### twopi — Radial Layout (`gvpy.engines.layout.twopi`)

BFS from root, concentric rings with angular span proportional to subtree size.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `root` | (auto) | Center node (graph or node attribute) |
| `ranksep` | `1.0` | Ring gap in inches (colon-separated for variable) |

### osage — Cluster Packing (`gvpy.engines.layout.osage`)

Recursive rectangular array packing within nested clusters. No hierarchical ranking.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `pack` / `packmode` | array | Packing algorithm |
| `sortv` | `0` | Sort value for array ordering |
| `margin` / `pad` | `18pt` | Cluster margin |

### patchwork — Treemap (`gvpy.engines.layout.patchwork`)

Squarified treemap where node area is proportional to the `area` attribute.

| Attribute | Default | Description |
|-----------|---------|-------------|
| `area` (node) | `1` | Node area weight |

## Simulation Engines

The simulation engines live under ``gvpy.engines.sim/`` (sibling to
``gvpy.engines.layout/``) and share the :class:`SimulationView` base
defined in ``gvpy/engines/sim/base.py``.  Both paradigms attach to a
:class:`Graph` via ``graph.attach_view(view)`` so a single graph can
host a layout view and a simulation view simultaneously.

The shared lifecycle contract is:

```python
class SimulationView(GraphView):
    def init() -> None        # build runtime state from graph topology
    def step() -> bool        # advance one event/iteration; False when done
    def reset() -> None       # restore initial state at t=0
    def run(until=None, max_steps=None)
    @property
    def now -> float          # current simulation time
    def is_done() -> bool
    def get_node_state(name) -> dict
    def to_json() -> dict     # round-trip to JSON (pictosync contract)
    def from_json(d) -> None
```

### Event-driven (`gvpy.engines.sim.events`) — SimPy-style

**Status:** Skeleton (working core, no resources/stores yet)

A minimal subset of the [SimPy](https://simpy.readthedocs.io) discrete-
event simulation API: priority queue keyed by ``(time, sequence)``,
processes implemented as generators that yield events to wait on,
callbacks fired when events trigger.

```python
from gvpy.engines.sim import Environment, EventSimulationView
from gvpy.core.graph import Graph

g = Graph(name="bench", directed=True)
view = EventSimulationView(g)
g.attach_view(view, name="sim")

def producer(env, name, period):
    while True:
        yield env.timeout(period)
        print(f"{name} fired at t={env.now}")

view.processes["A"] = view.env.process(producer(view.env, "A", 5))
view.processes["B"] = view.env.process(producer(view.env, "B", 3))
view.run(until=15)
```

| Class | Purpose |
|---|---|
| `Environment` | Heap-based priority queue + step loop |
| `Event` | Generic future occurrence with callback list |
| `Timeout` | Event scheduled at ``now + delay`` |
| `Process` | Wraps a generator; auto-resumes on yielded events |
| `EventSimulationView` | `SimulationView` wrapper holding the env + per-node processes |

### CBD synchronous block diagrams (`gvpy.engines.sim.cbd`) — PyCBD-style

**Status:** Skeleton (atomic primitives + hierarchical compounds + delay-cycle solver working)

Implements the [PyCBD](https://msdl.uantwerpen.be/git/yentl/PythonPDEVS-CBD)
Causal Block Diagram model with the **three-phase Mealy** simulation
semantics from Van Tendeloo & Vangheluwe (2018).  Each iteration runs:

1. **Output phase** — every block computes outputs from current inputs
   and current state, walked in topological order so upstream outputs
   are fresh by the time downstream blocks read them.
2. **Update phase** — every ``StatefulBlock`` computes its next state
   from the inputs of *this* iteration (Mealy semantics).
3. **Advance phase** — clock ticks; ``current_iter += 1``.

`DelayBlock` (``z⁻¹``) acts as the cycle-breaker: any feedback loop
must contain at least one delay so the topological sort can treat
delay outputs as graph sources.

```python
from gvpy.engines.sim import (
    CBDSimulationView, CompoundBlock,
    ConstantBlock, AdderBlock, DelayBlock,
)

# Integer ramp via Constant + Adder + Delay feedback
one   = ConstantBlock("one", value=1.0)
add   = AdderBlock("add", num_inputs=2)
delay = DelayBlock("delay", initial_state=0.0)

root = CompoundBlock("ramp")
root.add_block(one)
root.add_block(add)
root.add_block(delay)
root.add_connection("one",   "OUT", "add",   "IN1")
root.add_connection("delay", "OUT", "add",   "IN2")
root.add_connection("add",   "OUT", "delay", "IN")

view = CBDSimulationView(g, delta_t=1.0)
view.root = root
view.run(max_steps=5)
# add.OUT now equals 5.0 (the ramp 1, 2, 3, 4, 5)
```

| Class | Purpose |
|---|---|
| `Port` | Named input/output slot on a `Block` |
| `Connection` | Explicit `(src_port → dst_port)` link |
| `Block` | Atomic primitive (override `compute(curIter)`) |
| `StatefulBlock` | Block with internal state updated in phase 2 |
| `DelayBlock` | `z⁻¹` unit delay — algebraic-loop cycle breaker |
| `CompoundBlock` | Hierarchical container of sub-blocks + connections |
| `ConstantBlock`, `GainBlock`, `AdderBlock`, `NegatorBlock`, `ProductBlock` | Concrete primitives |
| `CBDSolver` | Three-phase Mealy step driver + topological sort |
| `CBDSimulationView` | `SimulationView` wrapper holding the root compound |

### Trace recorder (`gvpy.engines.sim.trace`)

`SimulationTrace` is an optional per-signal time-series recorder with
JSON round-trip.  Either paradigm's view can write samples to it
during a run for later inspection or regression testing:

```python
from gvpy.engines.sim import SimulationTrace

trace = SimulationTrace()
for _ in range(10):
    view.step()
    trace.record(view.now, "add.OUT", view.get_node_state("add")["OUT"])

series = trace.get_series("add.OUT")  # [(0.0, 1.0), (1.0, 2.0), ...]
```

## Graph Attributes Reference

Complete list of graph-level attributes. All attributes are available in the wizard's Graph tab unless marked "write-only".

| Attribute | Example CLI | Wizard | Description |
|-----------|-------------|:------:|-------------|
| `_background` | `-G_background="..."` | No | xdot background drawn behind the graph. Write-only — set by xdot renderer. |
| `bb` | — | No | Bounding box `"x1,y1,x2,y2"` in points. Write-only — computed by `_write_back()` after layout. |
| `beautify` | `-Gbeautify=true` | Yes | Arrange leaf nodes in circle around root (sfdp only). |
| `bgcolor` | `-Gbgcolor=lightgray` | Yes | Canvas background color. |
| `center` | `-Gcenter=true` | Yes | Center drawing in output canvas. |
| `charset` | `-Gcharset=UTF-8` | No | Character encoding for string input. Write-only — affects file loading, not layout. |
| `class` | `-Gclass=mygraph` | Yes | CSS classnames for SVG element. |
| `clusterrank` | `-Gclusterrank=global` | Yes | Cluster handling: `local`, `global`, `none` (dot only). |
| `colorscheme` | `-Gcolorscheme=x11` | Yes | Color scheme namespace for interpreting color names. |
| `comment` | `-Gcomment="note"` | Yes | Comment inserted into output. |
| `compound` | `-Gcompound=true` | Yes | Allow edges between clusters via `lhead`/`ltail` (dot only). |
| `concentrate` | `-Gconcentrate=true` | Yes | Merge parallel edges. |
| `Damping` | `-GDamping=0.95` | Yes | Force motion damping factor per iteration (neato only, default 0.99). |
| `defaultdist` | `-Gdefaultdist=2` | Yes | Distance between nodes in separate components (neato only). |
| `dim` | `-Gdim=3` | Yes | Dimensions for layout computation (neato, fdp, sfdp only, default 2). |
| `dimen` | `-Gdimen=3` | Yes | Dimensions for rendering (neato, fdp, sfdp only, default 2). |
| `diredgeconstraints` | `-Gdiredgeconstraints=true` | Yes | Constrain edges to point downwards (neato only). |
| `dpi` | `-Gdpi=150` | Yes | Pixels per inch for output (default 96). |
| `epsilon` | `-Gepsilon=0.001` | Yes | Convergence threshold for energy minimization (neato only). |
| `esep` | `-Gesep=5` | Yes | Margin around polygons for spline edge routing. |
| `fontcolor` | `-Gfontcolor=blue` | Yes | Default text color (default `black`). |
| `fontname` | `-Gfontname=Helvetica` | Yes | Default font face (default `Times-Roman`). |
| `fontnames` | `-Gfontnames=ps` | No | Font name representation in SVG. Write-only — affects SVG font output only. |
| `fontpath` | `-Gfontpath=/usr/share/fonts` | No | Directory list for bitmap font search. Write-only — runtime config. |
| `fontsize` | `-Gfontsize=18` | Yes | Default font size in points (default 14). |
| `forcelabels` | `-Gforcelabels=false` | Yes | Force placement of all xlabels even if overlapping (default `true`). |
| `gradientangle` | `-Ggradientangle=45` | Yes | Gradient fill angle in degrees. |
| `href` | `-Ghref="https://..."` | Yes | URL synonym for SVG/map/PS output. |
| `id` | `-Gid=graph1` | Yes | Identifier for SVG/map output. |
| `imagepath` | `-Gimagepath=./images` | No | Directories to search for image files. Write-only — runtime config. |
| `inputscale` | `-Ginputscale=72` | Yes | Scale applied to input `pos` values (neato, fdp only). |
| `K` | `-GK=0.5` | Yes | Spring constant / ideal edge length (fdp, sfdp only, default 0.3). |
| `label` | `-Glabel="My Graph"` | Yes | Graph title label text. |
| `label_scheme` | `-Glabel_scheme=1` | Yes | Treat `\|edgelabel\|*` nodes as edge labels (sfdp only). |
| `labeljust` | `-Glabeljust=l` | Yes | Graph/cluster label justification: `l`, `c`, `r` (default `c`). |
| `labelloc` | `-Glabelloc=t` | Yes | Graph label vertical position: `t` (top), `b` (bottom, default). |
| `landscape` | `-Glandscape=true` | Yes | Render in landscape orientation. |
| `layerlistsep` | — | No | Separator for layerRange splitting. Write-only — layer system not implemented. |
| `layers` | — | No | Ordered layer name list. Write-only — layer system not implemented. |
| `layerselect` | — | No | Layers to emit. Write-only — layer system not implemented. |
| `layersep` | — | No | Separator for layers attribute. Write-only — layer system not implemented. |
| `layout` | — | No | Layout engine name. Handled by `-K` flag / engine selector widget. |
| `levels` | `-Glevels=5` | Yes | Multilevel coarsening levels (sfdp only). |
| `levelsgap` | `-Glevelsgap=0.5` | Yes | Strictness of level constraints (neato only). |
| `lheight` | — | No | Graph/cluster label height in inches. Write-only — computed from label text. |
| `linelength` | — | No | Max chars before line overflow in text output. Write-only — affects text serialization. |
| `lp` | — | No | Label center position. Write-only — computed by `_compute_label_positions()`. |
| `lwidth` | — | No | Graph/cluster label width in inches. Write-only — computed from label text. |
| `margin` | `-Gmargin=0.5` | Yes | Canvas margins in inches. |
| `maxiter` | `-Gmaxiter=1000` | Yes | Maximum layout solver iterations (neato, fdp only). |
| `mclimit` | `-Gmclimit=2.0` | Yes | Scale factor for mincross edge crossing iterations (dot only). |
| `mindist` | `-Gmindist=1.5` | Yes | Minimum separation between all nodes (circo only, default 1.0). |
| `mode` | `-Gmode=KK` | Yes | Optimization algorithm: `major`, `KK`, `sgd`, `hier` (neato only). |
| `model` | `-Gmodel=circuit` | Yes | Distance matrix method: `shortpath`, `circuit`, `subset` (neato only). |
| `newrank` | `-Gnewrank=true` | Yes | Single global ranking ignoring clusters (dot only). |
| `nodesep` | `-Gnodesep=0.5` | Yes | Min horizontal space between same-rank nodes (dot only, default 0.25). |
| `nojustify` | `-Gnojustify=true` | Yes | Multiline text justification mode. |
| `normalize` | `-Gnormalize=true` | Yes | Normalize coordinates to origin (neato, fdp, sfdp, circo, twopi). |
| `notranslate` | `-Gnotranslate=true` | Yes | Suppress automatic translation to origin (neato only). |
| `nslimit` | `-Gnslimit=2` | Yes | Network simplex iteration limit for ranking (dot only). |
| `nslimit1` | `-Gnslimit1=2` | Yes | Network simplex iteration limit for X positioning (dot only). |
| `oneblock` | `-Goneblock=true` | Yes | Draw all components on one circle (circo only). |
| `ordering` | `-Gordering=out` | Yes | Left-to-right edge ordering: `in`, `out` (dot only). |
| `orientation` | `-Gorientation=landscape` | Yes | Graph orientation angle or landscape string. |
| `outputorder` | `-Goutputorder=nodesfirst` | Yes | Draw order: `breadthfirst`, `nodesfirst`, `edgesfirst`. |
| `overlap` | `-Goverlap=false` | Yes | Node overlap removal: `true`, `false`, `scale`, `prism`, `voronoi`. |
| `overlap_scaling` | `-Goverlap_scaling=-4` | Yes | Scale factor for overlap reduction. |
| `overlap_shrink` | `-Goverlap_shrink=true` | Yes | Compression pass after overlap removal. |
| `pack` | `-Gpack=true` | Yes | Pack disconnected components separately. |
| `packmode` | `-Gpackmode=clust` | Yes | How to pack: `node`, `clust`, `graph`, `array`. |
| `pad` | `-Gpad=0.5` | Yes | Extend drawing area beyond minimum in inches (default 0.0555). |
| `page` | — | No | Output page dimensions. Write-only — pagination not implemented. |
| `pagedir` | `-Gpagedir=TL` | Yes | Order in which pages are emitted. |
| `quadtree` | `-Gquadtree=fast` | Yes | Barnes-Hut quadtree mode: `normal`, `fast`, `none` (sfdp only). |
| `quantum` | `-Gquantum=10` | Yes | Round node dimensions to multiples of quantum. |
| `rankdir` | `-Grankdir=LR` | Yes | Layout direction: `TB`, `LR`, `BT`, `RL` (dot only). |
| `ranksep` | `-Granksep=1.0` | Yes | Separation between ranks / radial rings (dot, twopi). |
| `ratio` | `-Gratio=compress` | Yes | Aspect ratio: `compress`, `fill`, `auto`, or numeric. |
| `remincross` | `-Gremincross=true` | Yes | Run crossing minimization a second time (dot only). |
| `repulsiveforce` | `-Grepulsiveforce=2.0` | Yes | Repulsive force strength in FR model (sfdp only). |
| `resolution` | `-Gresolution=150` | Yes | Synonym for `dpi` — pixels per inch for output. |
| `root` | `-Groot=center` | Yes | Center node for radial/circular layout (twopi, circo). |
| `rotate` | `-Grotate=90` | Yes | Rotate drawing for landscape. |
| `rotation` | `-Grotation=45` | Yes | Counter-clockwise rotation of final layout in degrees (sfdp only). |
| `scale` | `-Gscale=2.0` | Yes | Scale layout after initial placement (neato, twopi). |
| `searchsize` | `-Gsearchsize=50` | Yes | Max negative-cut edges in network simplex search (dot only, default 30). |
| `sep` | `-Gsep=10` | Yes | Node margin for overlap removal routing. |
| `showboxes` | `-Gshowboxes=1` | Yes | Print debug guide boxes (dot only). |
| `size` | `-Gsize="8,10"` | Yes | Maximum drawing width and height in inches. |
| `smoothing` | `-Gsmoothing=spring` | Yes | Post-processing smoothing: `none`, `avg_dist`, `spring`, etc. (sfdp only). |
| `sortv` | — | No | Sort order for packmode packing. Write-only — used internally by packing. |
| `splines` | `-Gsplines=ortho` | Yes | Edge routing: `none`, `line`, `polyline`, `curved`, `ortho`, `spline`. |
| `start` | `-Gstart=42` | Yes | Initial node placement seed or method (neato, fdp, sfdp). |
| `style` | `-Gstyle=filled` | Yes | Style for graph/cluster border. |
| `stylesheet` | `-Gstylesheet=style.css` | Yes | URL of XML stylesheet for SVG output. |
| `target` | `-Gtarget=_blank` | Yes | Browser window for URL links in SVG/map. |
| `TBbalance` | `-GTBbalance=max` | Yes | Rank placement for floating nodes: `min`, `max`, `none` (dot only). |
| `tooltip` | `-Gtooltip="hover text"` | Yes | Mouse hover tooltip for SVG/cmap. |
| `truecolor` | — | No | Truecolor bitmap rendering. Write-only — bitmap output only. |
| `URL` | `-GURL="https://..."` | Yes | Hyperlink for graph in SVG/map/PS. |
| `viewport` | — | No | Clipping window on final drawing. Write-only — not implemented. |
| `voro_margin` | `-Gvoro_margin=0.1` | Yes | Voronoi margin tuning (neato, fdp, sfdp, circo, twopi). |
| `xdotversion` | — | No | xdot output format version. Write-only — xdot format only. |

**Summary:** 83 of 101 graph attributes are available in the wizard. The remaining 18 are write-only (computed by layout engines), runtime config (file paths), or format-specific (layer system, pagination, xdot).

## Node Attributes Reference

Complete list of node-level attributes. All attributes are available in the wizard's Node tab unless marked "write-only".

| Attribute | Example CLI | Wizard | Description |
|-----------|-------------|:------:|-------------|
| `area` | `-Narea=4` | Yes | Preferred area for node in squarified treemap (patchwork only, default 1). |
| `class` | `-Nclass=mynode` | Yes | CSS classnames for SVG element. |
| `color` | `-Ncolor=red` | Yes | Node border/outline color (default `black`). |
| `colorscheme` | `-Ncolorscheme=x11` | Yes | Color scheme namespace for interpreting color names. |
| `comment` | `-Ncomment="note"` | Yes | Comment inserted into output. |
| `distortion` | `-Ndistortion=0.5` | Yes | Distortion factor for `shape=polygon` (default 0). |
| `fillcolor` | `-Nfillcolor=lightblue` | Yes | Node fill color (default `lightgrey`). |
| `fixedsize` | `-Nfixedsize=true` | Yes | Use exact `width`/`height` rather than fitting label. |
| `fontcolor` | `-Nfontcolor=blue` | Yes | Node label text color (default `black`). |
| `fontname` | `-Nfontname=Courier` | Yes | Node label font face (default `Times-Roman`). |
| `fontsize` | `-Nfontsize=18` | Yes | Node label font size in points (default 14). |
| `gradientangle` | `-Ngradientangle=90` | Yes | Gradient fill angle for node. |
| `group` | `-Ngroup=cluster1` | Yes | Group name for keeping nodes near each other (dot only). |
| `height` | `-Nheight=1.0` | Yes | Node height in inches (default 0.5). |
| `href` | `-Nhref="https://..."` | Yes | URL synonym for SVG/map/PS. |
| `id` | `-Nid=node1` | Yes | SVG/map identifier. |
| `image` | `-Nimage=icon.png` | Yes | Image file to display inside node. |
| `imagepos` | `-Nimagepos=tl` | Yes | Image position within node (default `mc`). |
| `imagescale` | `-Nimagescale=true` | Yes | How image fills the node. |
| `K` | `-NK=0.5` | Yes | Per-node spring constant override (fdp, sfdp only). |
| `label` | `-Nlabel="Node A"` | Yes | Node label text (default: node name). |
| `labelloc` | `-Nlabelloc=t` | Yes | Vertical label placement within node (default `c`). |
| `layer` | — | No | Layer membership. Write-only — layer system not implemented. |
| `margin` | `-Nmargin=0.1` | Yes | Margin between label and node boundary. |
| `nojustify` | `-Nnojustify=true` | Yes | Multiline label justification mode. |
| `ordering` | `-Nordering=out` | Yes | Per-node left-to-right edge ordering (dot only). |
| `orientation` | `-Norientation=45` | Yes | Node shape rotation angle in degrees (default 0). |
| `penwidth` | `-Npenwidth=2` | Yes | Width of node border pen in points (default 1). |
| `peripheries` | `-Nperipheries=2` | Yes | Number of border rings around node. |
| `pin` | `-Npin=true` | Yes | Lock node at its input `pos` coordinate (neato, fdp only). |
| `pos` | — | No | Node position `"x,y"`. Write-only — computed by `_write_back()` after layout. |
| `rects` | — | No | Record field rectangles in points. Write-only — computed by dot for record shapes. |
| `regular` | `-Nregular=true` | Yes | Force polygon to be regular (equal sides/angles). |
| `root` | `-Nroot=true` | Yes | Mark this node as the layout root (twopi, circo only). |
| `samplepoints` | — | No | Points used to approximate circle/ellipse. Write-only — internal rendering parameter. |
| `shape` | `-Nshape=box` | Yes | Node shape (default `ellipse`). 20+ shapes supported. |
| `shapefile` | — | No | External file for custom node shape. Write-only — runtime file reference. |
| `showboxes` | `-Nshowboxes=1` | Yes | Debug guide boxes for node (dot only). |
| `sides` | `-Nsides=6` | Yes | Side count for `shape=polygon` (default 4). |
| `skew` | `-Nskew=0.5` | Yes | Skew factor for `shape=polygon` (default 0). |
| `sortv` | — | No | Sort value for pack ordering. Write-only — used internally by packing. |
| `style` | `-Nstyle=filled` | Yes | Node style: `filled`, `dashed`, `dotted`, `rounded`, `bold`, `invis`. |
| `target` | `-Ntarget=_blank` | Yes | Browser window for URL in SVG/map. |
| `tooltip` | `-Ntooltip="hover"` | Yes | Mouse hover tooltip for SVG/cmap. |
| `URL` | `-NURL="https://..."` | Yes | Hyperlink for node in SVG/map/PS. |
| `vertices` | — | No | Custom polygon vertex list. Write-only — computed after layout. |
| `width` | `-Nwidth=1.5` | Yes | Node width in inches (default 0.75). |
| `xlabel` | `-Nxlabel="extra"` | Yes | External label placed outside node boundary. |
| `xlp` | — | No | External label position. Write-only — computed by `_compute_label_positions()`. |
| `z` | `-Nz=1.0` | Yes | Z-coordinate for 3D layouts (neato, fdp only, default 0). |

**Summary:** 41 of 49 node attributes are available in the wizard. The remaining 8 are write-only (positions, vertices, rectangles computed by layout engines).

## Edge Attributes Reference

Complete list of edge-level attributes. All attributes are available in the wizard's Edge tab unless marked "write-only".

| Attribute | Example CLI | Wizard | Description |
|-----------|-------------|:------:|-------------|
| `arrowhead` | `-Earrowhead=vee` | Yes | Arrowhead shape at head node (default `normal`). |
| `arrowsize` | `-Earrowsize=1.5` | Yes | Arrowhead scale multiplier (default 1). |
| `arrowtail` | `-Earrowtail=dot` | Yes | Arrowhead shape at tail node (default `normal`). |
| `class` | `-Eclass=myedge` | Yes | CSS classnames for SVG element. |
| `color` | `-Ecolor=red` | Yes | Edge line color (default `black`). |
| `colorscheme` | `-Ecolorscheme=x11` | Yes | Color scheme namespace. |
| `comment` | `-Ecomment="note"` | Yes | Comment inserted into output. |
| `constraint` | `-Econstraint=false` | Yes | Whether edge participates in rank assignment (dot only, default `true`). |
| `decorate` | `-Edecorate=true` | Yes | Draw line connecting edge label to edge. |
| `dir` | `-Edir=both` | Yes | Arrow direction: `forward`, `back`, `both`, `none` (default `forward`). |
| `edgehref` | `-Eedgehref="..."` | Yes | Synonym for `edgeURL` for SVG/map. |
| `edgetarget` | `-Eedgetarget=_blank` | Yes | Browser window for `edgeURL` link. |
| `edgetooltip` | `-Eedgetooltip="info"` | Yes | Tooltip on non-label part of edge. |
| `edgeURL` | `-EedgeURL="https://..."` | Yes | URL for non-label part of edge. |
| `fillcolor` | `-Efillcolor=yellow` | Yes | Fill color for edge arrowheads (default `black`). |
| `fontcolor` | `-Efontcolor=blue` | Yes | Edge label text color (default `black`). |
| `fontname` | `-Efontname=Courier` | Yes | Edge label font face (default `Times-Roman`). |
| `fontsize` | `-Efontsize=10` | Yes | Edge label font size in points (default 14). |
| `head_lp` | — | No | Head label center position. Write-only — computed by `_compute_label_positions()`. |
| `headclip` | `-Eheadclip=false` | Yes | Clip edge to head node boundary (default `true`). |
| `headhref` | `-Eheadhref="..."` | Yes | URL for head of edge in SVG/map. |
| `headlabel` | `-Eheadlabel="H"` | Yes | Text label at head end of edge. |
| `headport` | `-Eheadport=n` | Yes | Compass port on head node (default `center`). |
| `headtarget` | `-Eheadtarget=_blank` | Yes | Browser window for `headURL`. |
| `headtooltip` | `-Eheadtooltip="tip"` | Yes | Tooltip on head label. |
| `headURL` | `-EheadURL="..."` | Yes | URL for head label in SVG/map. |
| `href` | `-Ehref="https://..."` | Yes | URL synonym for SVG/map/PS. |
| `id` | `-Eid=edge1` | Yes | SVG/map identifier. |
| `label` | `-Elabel="connects"` | Yes | Edge label text. |
| `labelangle` | `-Elabelangle=-25` | Yes | Polar angle for head/tail label positioning (default -25). |
| `labeldistance` | `-Elabeldistance=2` | Yes | Scale factor for head/tail label distance from node (default 1). |
| `labelfloat` | `-Elabelfloat=true` | Yes | Allow label to float to reduce edge crossings. |
| `labelfontcolor` | `-Elabelfontcolor=red` | Yes | Head/tail label text color (default `black`). |
| `labelfontname` | `-Elabelfontname=Arial` | Yes | Head/tail label font face. |
| `labelfontsize` | `-Elabelfontsize=10` | Yes | Head/tail label font size in points (default 14). |
| `labelhref` | `-Elabelhref="..."` | Yes | URL for label in SVG/map. |
| `labeltarget` | `-Elabeltarget=_blank` | Yes | Browser window for `labelURL`. |
| `labeltooltip` | `-Elabeltooltip="tip"` | Yes | Tooltip on label. |
| `labelURL` | `-ElabelURL="..."` | Yes | URL for label in SVG/map. |
| `layer` | — | No | Layer membership. Write-only — layer system not implemented. |
| `len` | `-Elen=2.0` | Yes | Preferred edge length in inches (neato, fdp only, default 1.0). |
| `lhead` | `-Elhead=cluster_0` | Yes | Logical head cluster for edge termination (dot only, requires `compound=true`). |
| `lp` | — | No | Label center position. Write-only — computed by layout. |
| `ltail` | `-Eltail=cluster_1` | Yes | Logical tail cluster for edge origination (dot only, requires `compound=true`). |
| `minlen` | `-Eminlen=2` | Yes | Minimum rank difference between head and tail (dot only, default 1). |
| `nojustify` | `-Enojustify=true` | Yes | Multiline label justification mode. |
| `penwidth` | `-Epenwidth=2` | Yes | Pen width for edge line in points (default 1). |
| `pos` | — | No | Spline control points. Write-only — computed by `_write_back()` after layout. |
| `radius` | `-Eradius=5` | Yes | Radius of rounded corners on orthogonal edges (default 0). |
| `samehead` | `-Esamehead=port1` | Yes | Edges with same head + samehead share a head port (dot only). |
| `sametail` | `-Esametail=port1` | Yes | Edges with same tail + sametail share a tail port (dot only). |
| `showboxes` | `-Eshowboxes=1` | Yes | Debug guide boxes for edge routing (dot only). |
| `style` | `-Estyle=dashed` | Yes | Edge style: `solid`, `dashed`, `dotted`, `bold`, `invis`. |
| `tail_lp` | — | No | Tail label center position. Write-only — computed by `_compute_label_positions()`. |
| `tailclip` | `-Etailclip=false` | Yes | Clip edge to tail node boundary (default `true`). |
| `tailhref` | `-Etailhref="..."` | Yes | URL for tail of edge in SVG/map. |
| `taillabel` | `-Etaillabel="T"` | Yes | Text label at tail end of edge. |
| `tailport` | `-Etailport=s` | Yes | Compass port on tail node (default `center`). |
| `tailtarget` | `-Etailtarget=_blank` | Yes | Browser window for `tailURL`. |
| `tailtooltip` | `-Etailtooltip="tip"` | Yes | Tooltip on tail label. |
| `tailURL` | `-EtailURL="..."` | Yes | URL for tail label in SVG/map. |
| `target` | `-Etarget=_blank` | Yes | Browser window for URL in SVG/map. |
| `tooltip` | `-Etooltip="hover"` | Yes | Mouse hover tooltip for SVG/cmap. |
| `URL` | `-EURL="https://..."` | Yes | Hyperlink for edge in SVG/map/PS. |
| `weight` | `-Eweight=5` | Yes | Edge weight: rank importance in dot, spring strength in neato/fdp (default 1). |
| `xlabel` | `-Exlabel="extra"` | Yes | External label outside edge path. |
| `xlp` | — | No | External label position. Write-only — computed by `_compute_label_positions()`. |

**Summary:** 61 of 68 edge attributes are available in the wizard. The remaining 7 are write-only (label positions, spline control points computed by layout engines).

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
from gvpy.engines.layout.dot import DotLayout
from gvpy.engines.layout.circo import CircoLayout
from gvpy.engines import get_engine

# Full pipeline
graph = read_gv('digraph G { a -> b -> c; }')
result = DotLayout(graph).layout()
svg = render_svg(result)
```

## Graph Tools (`gvtools.py`)

`gvtools.py` provides graph analysis, transformation, and generation utilities — the Python equivalents of Graphviz standalone commands like `acyclic`, `tred`, `gc`, `gvgen`, etc.

### Usage

```bash
python gvtools.py <tool> [options] [file]
python gvtools.py --list              # list all tools
```

### Available Tools

| Tool | Graphviz equivalent | Description |
|------|-------------------|-------------|
| `acyclic` | `acyclic` | Break cycles by reversing edges |
| `tred` | `tred` | Transitive reduction — remove implied edges |
| `unflatten` | `unflatten` | Improve layout aspect ratio by staggering chains |
| `ccomps` | `ccomps` | Extract connected components |
| `bcomps` | `bcomps` | Extract biconnected components + articulation points |
| `sccmap` | `sccmap` | Strongly connected components (Tarjan's algorithm) |
| `gc` | `gc` | Graph statistics — count nodes, edges, components |
| `nop` | `nop` | Canonicalize / pretty-print DOT |
| `gvgen` | `gvgen` | Generate standard graphs (complete, cycle, grid, etc.) |
| `gvcolor` | `gvcolor` | Color nodes by component or degree |
| `edgepaint` | `edgepaint` | Color edges to reduce crossing confusion |
| `mingle` | `mingle` | Edge bundling — reduce clutter in dense graphs |

### Tool CLI Flags

Each tool supports `-?` for usage help:

```bash
python gvtools.py acyclic -?
python gvtools.py gc -?
python gvtools.py gvgen -?
```

**acyclic** — `acyclic [-nv?] [-o outfile] <file>`

| Flag | Description |
|------|-------------|
| `-n` | Do not output graph (check only) |
| `-v` | Verbose (report to stderr) |
| `-o file` | Write output to file |

**tred** — `tred [-vr?] [-o FILE] <files>`

| Flag | Description |
|------|-------------|
| `-v` | Verbose |
| `-r` | Print removed edges to stderr |
| `-o FILE` | Redirect output to file |

**unflatten** — `unflatten [-f?] [-l M] [-c N] [-o outfile] <files>`

| Flag | Description |
|------|-------------|
| `-f` | Adjust immediate fanout chains |
| `-l M` | Stagger leaf edge length between [1, M] |
| `-c N` | Chain disconnected nodes in groups of N |
| `-o file` | Write output to file |

**ccomps** — `ccomps [-svxz?] [-o template] <files>`

| Flag | Description |
|------|-------------|
| `-s` | Silent (print count only) |
| `-v` | Verbose |
| `-x` | Emit components as separate root graphs |
| `-z` | Sort by size, largest first |
| `-o template` | Output file template |

**bcomps** — `bcomps [-stvx?] [-o template] <files>`

| Flag | Description |
|------|-------------|
| `-s` | Don't print components |
| `-t` | Emit block-cutpoint tree |
| `-v` | Verbose |
| `-x` | Emit blocks as root graphs |
| `-o template` | Output file template |

**sccmap** — `sccmap [-sSdv?] [-o outfile] <files>`

| Flag | Description |
|------|-------------|
| `-s` | Statistics only (no component output) |
| `-S` | Silent (no stderr) |
| `-d` | Include degenerate (single-node) components |
| `-v` | Verbose |
| `-o file` | Write output to file |

**gc** — `gc [-necCaDUrsv?] <files>`

| Flag | Description |
|------|-------------|
| `-n` | Print number of nodes |
| `-e` | Print number of edges |
| `-c` | Print number of connected components |
| `-C` | Print number of clusters |
| `-a` | Print all counts |
| `-D` | Only directed graphs |
| `-U` | Only undirected graphs |
| `-r` | Recursively analyze subgraphs |
| `-s` | Silent |

**nop** — `nop [-p?] <files>`

| Flag | Description |
|------|-------------|
| `-p` | Parse-only (validate DOT without output) |

**gvgen** — `gvgen [-dv?] [options]`

| Flag | Description |
|------|-------------|
| `-k<n>` | Complete graph K_n |
| `-c<n>` | Cycle C_n |
| `-p<n>` | Path P_n |
| `-s<n>` | Star S_n |
| `-g<r,c>` | Grid r × c |
| `-t<d>` | Binary tree depth d |
| `-d` | Directed graph |
| `-o file` | Write output to file |

Also accepts named types: `petersen`

**gvcolor** — `gvcolor [-?] [mode=component\|degree] <files>`

| Flag | Description |
|------|-------------|
| `mode=component` | Color by connected component (default) |
| `mode=degree` | Color by node degree |

**edgepaint** — `edgepaint [-v?] [-o fname] <file>`

| Flag | Description |
|------|-------------|
| `--angle=a` | Min crossing angle in degrees (default 15) |
| `--color_scheme=c` | Palette: rgb, gray, lab, or hex list |
| `--share_endpoint` | Edges sharing endpoints not conflicting |
| `-v` | Verbose |
| `-o fname` | Write output to file |

**mingle** — `mingle <options> <file>`

| Flag | Default | Description |
|------|---------|-------------|
| `-a t` | 40 | Max turning angle [0-180] |
| `-c i` | 1 | Compatibility: 0=distance, 1=full |
| `-i iter` | 4 | Outer iterations/subdivisions |
| `-k k` | 10 | Nearest neighbor graph size |
| `-K k` | — | Force constant |
| `-m method` | 1 | 0=force directed, 1=agglom ink, 2=cluster |
| `-o fname` | stdout | Output file |
| `-p t` | — | Sharp angle balance |
| `-r R` | 100 | Max recursion level |
| `-T fmt` | gv | Output format: gv or simple |
| `-v` | — | Verbose |

### Examples

```bash
# Graph statistics
python gvtools.py gc -a input.gv

# Break cycles and show what changed
python gvtools.py acyclic -v input.gv -o acyclic.gv

# Find strongly connected components
python gvtools.py sccmap -d input.gv

# Biconnected components with block-cutpoint tree
python gvtools.py bcomps -t input.gv

# Generate standard graphs
python gvtools.py gvgen -k8                    # complete K8
python gvtools.py gvgen -c12                   # cycle C12
python gvtools.py gvgen -g4,6                  # 4x6 grid
python gvtools.py gvgen -t4 -d                 # directed binary tree
python gvtools.py gvgen petersen               # Petersen graph

# Color nodes by degree
python gvtools.py gvcolor mode=degree input.gv | python gvcli.py - -Tsvg -o colored.svg

# Bundle edges after layout
python gvcli.py -Kneato input.gv -Tsvg --bundle -o bundled.svg
```

### Python API

```python
from gvpy.tools.gc import graph_stats
from gvpy.tools.ccomps import connected_components
from gvpy.tools.bcomps import biconnected_components
from gvpy.tools.sccmap import strongly_connected_components
from gvpy.tools.gvgen import generate_complete, generate_petersen, generate_grid
from gvpy.tools.gvcolor import color_by_component, color_by_degree
from gvpy.tools.edgepaint import edgepaint
from gvpy.tools.mingle import MingleBundler
```

## Project Structure

```
GraphvizPy/
├── gvcli.py                      # Unified CLI (all engines, all formats)
├── gvtools.py                    # Graph tools CLI (analysis, transforms, generation)
├── dot.py                        # Wrapper: calls gvcli.py with -Kdot default
├── pyproject.toml                # Package definition (pip install -e .)
│
├── gvpy/                         # Main Python package
│   │
│   ├── core/                     # Graph data structures (port of Graphviz cgraph)
│   │   ├── graph.py              #   Graph class with mixin architecture
│   │   ├── node.py               #   Node and CompoundNode
│   │   ├── edge.py               #   Edge with half-edge pairs
│   │   ├── graph_view.py         #   GraphView abstract base (view-architecture root)
│   │   ├── headers.py            #   Agclos, Agdesc, AgIdDisc, callbacks
│   │   ├── defines.py            #   ObjectType, EdgeType, GraphEvent enums
│   │   ├── agobj.py              #   Base class for graph objects
│   │   ├── error.py              #   Logging and error handling
│   │   ├── _graph_apply.py       #   subnode_search, subedge_search, subgraph_search
│   │   ├── _graph_attrs.py       #   AttrMixin (graph/node/edge attributes)
│   │   ├── _graph_callbacks.py   #   CallbackMixin (event hooks)
│   │   ├── _graph_cmpnd.py       #   Agcmpgraph + agfindhidden (compound nodes)
│   │   ├── _graph_edges.py       #   EdgeMixin + module-level C-API edge functions
│   │   ├── _graph_id.py          #   IdMixin + agnextseq
│   │   ├── _graph_nodes.py       #   NodeMixin
│   │   ├── _graph_subgraphs.py   #   SubgraphMixin
│   │   └── _graph_traversal.py   #   gather_all_nodes/edges/subgraphs, get_root_graph
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
│   ├── engines/                  # Engine sub-packages (layout + simulation)
│   │   ├── __init__.py           #   Engine registry: get_engine(), list_engines()
│   │   │
│   │   ├── layout/               # Layout engines (all implemented)
│   │   │   ├── __init__.py
│   │   │   ├── base.py           #   LayoutView, LayoutEngine
│   │   │   ├── font_metrics.py   #   Text width measurement
│   │   │   ├── layout_features.py#   Attribute table per engine
│   │   │   ├── wizard.py         #   Interactive PyQt6 layout wizard
│   │   │   ├── dot/              #   Hierarchical layout (Sugiyama, 5 phases)
│   │   │   │   ├── dot_layout.py    #     DotGraphInfo / DotLayout entry point
│   │   │   │   ├── dotinit.py       #     Init helpers (cgraph -> DotGraphInfo)
│   │   │   │   ├── rank.py          #     Phase 1 — rank assignment
│   │   │   │   ├── mincross.py      #     Phase 2 — crossing minimization
│   │   │   │   ├── position.py      #     Phase 3 — coordinate assignment
│   │   │   │   ├── splines.py       #     Phase 4 driver + dispatch
│   │   │   │   ├── path.py          #     Path/PathEnd/Box data, beginpath/endpath
│   │   │   │   ├── routespl.py      #     Box-corridor router (checkpath, routesplines)
│   │   │   │   ├── clip.py          #     Bezier clip-to-node-boundary
│   │   │   │   ├── regular_edge.py  #     Regular-edge routing (virtual chain walk)
│   │   │   │   ├── flat_edge.py     #     Flat (same-rank) edge routing
│   │   │   │   ├── self_edge.py     #     Self-loop routing (4 compass variants)
│   │   │   │   ├── straight_edge.py #     splines=line / splines=curved routing
│   │   │   │   ├── pathplan/        #     Pathplan library port (route, visibility,
│   │   │   │   │                    #     shortestpath, triangulation, solvers)
│   │   │   │   ├── cluster.py       #     Cluster discovery + post-pos cleanup
│   │   │   │   └── ns_solver.py     #     Network simplex solver
│   │   │   ├── neato/            #   Spring-model (stress majorization / KK / SGD)
│   │   │   ├── fdp/              #   Force-directed (Fruchterman-Reingold + grid)
│   │   │   ├── sfdp/             #   Scalable force-directed (multilevel + quadtree)
│   │   │   ├── circo/            #   Circular (biconnected decomposition)
│   │   │   ├── twopi/            #   Radial (BFS concentric rings)
│   │   │   ├── osage/            #   Cluster packing (rectangular array)
│   │   │   └── patchwork/        #   Treemap (squarified rectangles)
│   │   │
│   │   └── sim/                  # Simulation engines (skeleton)
│   │       ├── __init__.py       #   Public re-exports
│   │       ├── base.py           #   SimulationView abstract intermediate
│   │       ├── clock.py          #   Clock protocol + Discrete/Continuous clocks
│   │       ├── events.py         #   SimPy-style: Environment, Event, Timeout, Process
│   │       ├── cbd.py            #   PyCBD-style: Block, CompoundBlock, primitives
│   │       ├── solver.py         #   Three-phase Mealy step + topological sort
│   │       └── trace.py          #   SimulationTrace per-signal recorder
│   │
│   ├── render/                   # Output rendering and format I/O
│   │   ├── svg_renderer.py       #   Layout dict → SVG
│   │   ├── json_io.py            #   Graphviz JSON/JSON0 read/write
│   │   └── gxl_io.py             #   GXL (XML) read/write
│   │
│   └── tools/                    # Graph utilities (analysis, transforms, generation)
│       ├── acyclic.py            #   Break cycles
│       ├── tred.py               #   Transitive reduction
│       ├── unflatten.py          #   Improve aspect ratio
│       ├── ccomps.py             #   Connected components
│       ├── bcomps.py             #   Biconnected components
│       ├── sccmap.py             #   Strongly connected components
│       ├── gc.py                 #   Graph statistics
│       ├── nop.py                #   Pretty-print DOT
│       ├── gvgen.py              #   Generate standard graphs
│       ├── gvcolor.py            #   Color nodes by component/degree
│       ├── edgepaint.py          #   Color crossing edges
│       └── mingle.py             #   Edge bundling post-processor
│
├── test_data/                    # Test files (.gv, .dot, .json, .gxl)
│
├── tests/                        # pytest test suite
│   ├── test_cgraph_api.py        #   Core API
│   ├── test_node_operations.py   #   Node CRUD
│   ├── test_edge_operations.py   #   Edge CRUD
│   ├── test_subgraph_operations.py #  Subgraph CRUD
│   ├── test_callbacks.py         #   Callback system
│   ├── test_graph_core.py        #   Graph init, attrs, algorithms
│   ├── test_compound_nodes.py    #   Compound nodes
│   ├── test_dot_parser.py        #   DOT parser
│   ├── test_dot_layout.py        #   Dot layout + attributes (238 tests)
│   ├── test_phase4_coverage.py   #   Phase 4 spline module coverage (47 tests)
│   ├── test_svg_renderer.py      #   SVG rendering
│   ├── test_formats.py           #   Format roundtrip
│   ├── test_circo_layout.py      #   Circo layout
│   ├── test_neato_layout.py      #   Neato layout
│   ├── test_fdp_layout.py        #   Fdp layout
│   ├── test_sfdp_layout.py       #   Sfdp layout
│   ├── test_twopi_layout.py      #   Twopi layout
│   ├── test_osage_layout.py      #   Osage layout
│   ├── test_patchwork_layout.py  #   Patchwork layout
│   ├── test_mingle.py            #   Mingle bundling
│   ├── test_sim_skeleton.py      #   Sim engines smoke tests
│   └── test_all_files.py         #   Bulk file validation
│
├── tools/
│   └── run_all_dots.py           # Bulk-test all test_data/*.dot files
│                                 # through Python + C dot.exe, writes
│                                 # side-by-side results to test_run.md
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

## Current Status

The codebase is in active refactor toward the view-architecture model
described above.  Recent milestones (see ``TODO_core_refactor.md`` for
the full timeline):

- ✅ **Core split** — `gvpy/core/graph.py` was 1680 lines mixing the
  `Graph` class with C-API helpers.  Helpers are now broken out into
  per-concern modules (`_graph_apply.py`, `_graph_cmpnd.py`,
  `_graph_traversal.py`, `_graph_edges.py`, `_graph_id.py`) matching
  Graphviz `lib/cgraph/` factoring.  `graph.py` is now 1329 lines
  with re-exports for backward compatibility.
- ✅ **Layout engines under `engines/layout/`** — All eight layout
  engines plus shared helpers (`base.py`, `font_metrics.py`,
  `layout_features.py`, `wizard.py`) live under
  `gvpy/engines/layout/` so the sibling `gvpy/engines/sim/`
  namespace is free for simulation engines.
- ✅ **Dot engine extracted into per-phase modules** —
  `gvpy/engines/layout/dot/dot_layout.py` was 6739 lines; it is now
  ~2000 lines after extracting Phase 1 (`rank.py`), Phase 2
  (`mincross.py`), Phase 3 (`position.py`), Phase 4 (`splines.py`),
  the network simplex solver (`ns_solver.py`), cluster geometry
  (`cluster.py`), and init helpers (`dotinit.py`).  Each phase
  has full C-source traceability (file + line number per function).
- ✅ **Dot splines port (Phases A–G complete)** — The entire
  spline-routing pipeline has been ported function-by-function from
  Graphviz `lib/dotgen/dotsplines.c` + `lib/common/splines.c` +
  `lib/common/routespl.c` + `lib/pathplan/*`:
  - **Phase A** (`splines.py`) — driver shell, edge classification, bbox family
  - **Phase B** (`pathplan/*.py`, `routespl.py`, `path.py`) — pathplan
    library + box-corridor router + `beginpath`/`endpath`
  - **Phase C** (`clip.py`) — bezier clip, shape clip, `clip_and_install`
  - **Phase D** (`regular_edge.py`) — regular-edge routing through
    virtual node chains
  - **Phase E** (`flat_edge.py`) — flat (same-rank) edge arc corridors
  - **Phase F** (`self_edge.py`) — self-loop routing (4 compass variants)
  - **Phase G** (`straight_edge.py`) — straight/curved edges with
    cycle-centroid bending for `splines=line` / `splines=curved`

  ~100 C functions ported across 7 new modules.  On the 199-file
  test_data corpus: Python 175 OK, C dot.exe 159 OK
  (both with same 4-column result format: `N nodes, E edges, R routed`).
- ✅ **Parser robustness** — `read_dot` now sanitizes non-ASCII bytes
  and handles multi-graph files, so corrupted / ISO-8859-encoded /
  fuzz-test DOT files no longer fail to parse.
- ✅ **DotGraphInfo refactor** — Removed 77 function-local imports
  by hoisting satellite-module imports to top of `dot_layout.py`;
  renamed misleading `self` parameter on 6 staticmethod module
  aliases to reflect the actual argument type (`ln`, `le`, `pts`,
  `inside`).
- ✅ **`SimulationView` skeleton** — `gvpy/engines/sim/` provides
  the abstract `SimulationView` base, SimPy-style event-driven
  primitives (`Environment`, `Event`, `Timeout`, `Process`,
  `EventSimulationView`), PyCBD-style synchronous block diagrams
  (`Block`, `StatefulBlock`, `DelayBlock`, `CompoundBlock`,
  `CBDSimulationView`), and the three-phase Mealy `CBDSolver`.
  9 smoke tests cover both paradigms end-to-end.
- ⏳ **Pictosync engine** — `PictoGraphInfo(LayoutView)` is the
  next planned addition (Step 9 in `TODO_core_refactor.md`).

## Test Coverage

| Component | Tests | Status |
|---|---|---|
| DOT parser | 44 | All pass |
| Dot layout + labels | 238 | All pass |
| Phase 4 spline coverage tests | 47 | All pass |
| Neato layout | 27 | All pass |
| Fdp layout | 16 | All pass |
| Sfdp layout | 16 | All pass |
| Circo layout | 25 | All pass |
| Twopi layout | 17 | All pass |
| Osage layout | 16 | All pass |
| Patchwork layout | 17 | All pass |
| Mingle bundling | 18 | All pass |
| SVG renderer | 18 | All pass |
| Core API | 100+ | All pass |
| Format I/O (DOT/JSON/GXL) | 71 | All pass |
| Sim engines (event + CBD smoke tests) | 9 | All pass |
| Bulk DOT file run (`tools/run_all_dots.py`) | 199 files | 175 OK, 4 FAIL, 16 TIMEOUT, 4 SLOW |
| **Total (unit tests)** | **285** | **All pass** |

**Phase 4 module coverage** (after `tools/run_all_dots.py` + targeted
unit tests): `pathplan/route.py` 94%, `pathplan/shortest.py` 96%,
`pathplan/solvers.py` 97%, `clip.py` 95%, `routespl.py` 90%,
`regular_edge.py` 82%, `self_edge.py` 98%, `straight_edge.py` 84%,
`flat_edge.py` 61%, `path.py` 76%.  Overall new-code coverage: 76%.

## Hierarchical Layout Algorithm (dot engine)

This section explains how the `dot` layout engine positions nodes and clusters,
using `test_data/aa1332.dot` (a real-world signal-processing dataflow graph) as
a running example.  The file has `rankdir=LR` (left-to-right), so ranks run
horizontally and the cross-rank axis is vertical.

### Overview: Four Phases

The Sugiyama framework lays out a directed graph in four phases:

```
Phase 1 ─ Rank Assignment     (which column does each node go in?)
Phase 2 ─ Crossing Minimization (which row within the column?)
Phase 3 ─ Coordinate Assignment (exact X, Y in points)
Phase 4 ─ Edge Routing          (polyline / spline paths)
```

### Phase 1 — Rank Assignment

**What is a rank?**  A rank is a vertical slice (column in LR mode) that
groups nodes at the same depth in the directed graph.  Edges flow from lower
ranks to higher ranks.

Network simplex assigns each node an integer rank so that every edge
`tail -> head` satisfies `rank(head) - rank(tail) >= minlen` (usually 1).
The solver minimizes `sum(weight * length)` across all edges.

For `aa1332.dot`, this produces 23 ranks (0..22).  Here are the first few:

```
 Rank 0 (x=67)     Rank 1 (x=162)   Rank 2 (x=272)   Rank 3 (x=382)
 ┌──────────┐       ┌──────────┐     ┌──────────┐     ┌────────────────┐
 │  c4119   │       │  c4139   │     │  c4114   │     │  c4115         │
 │  54x50pt │       │  64x50pt │     │  54x50pt │     │  64x50pt       │
 └──────────┘       └──────────┘     └──────────┘     └────────────────┘
 ┌──────────┐       ┌──────────┐     ┌──────────┐     ┌────────────────┐
 │  c4137   │       │  c4138   │     │  c4140   │     │     c4047      │
 │  54x50pt │       │  64x50pt │     │  84x50pt │     │  103x148pt (!) │
 └──────────┘       └──────────┘     └──────────┘     └────────────────┘
                                                       ┌────────────────┐
                                                       │  c4141         │
                                                       │  56x37pt       │
                                                       └────────────────┘
```

The **tallest node in rank 3** is `c4047` at 148pt.  This height determines the
inter-rank spacing: every rank is separated by at least `ranksep` (default 18pt)
plus the half-heights of the tallest nodes in adjacent ranks.

### Cluster Hierarchy

`aa1332.dot` has a deep cluster hierarchy.  Clusters are subgraphs whose names
start with `cluster`.  Here is the tree (showing the green DarkGreen borders):

```
cluster_6754  (outermost green box, 90 nodes)
├── cluster_4252  (29 nodes)
│   ├── cluster_4117  (c4114, c4115, c4116)
│   ├── cluster_4144
│   │   ├── clusterc4119  (c4119)
│   │   ├── clusterc4143  (c4143)
│   │   └── cluster_4142  (c4137, c4138, c4139, c4140, c4141)
│   ├── cluster_4148  (c4146, c4147)
│   └── cluster_4250  (11 nodes)
│       └── cluster_4246  (c4243, c4244, c4245)
├── cluster_4257  (c4255, c4256)
├── cluster_5378
│   └── cluster_5376  (c5372, c5373, c5374, c5375)
├── cluster_5383  (c5381, c5382)
├── cluster_6382  (c6379, c6380, c6381)
├── cluster_6409
│   └── cluster_6407  (c6402, c6403, c6404, c6405, c6406)
├── cluster_6413  (c6411, c6412)
└── cluster_6752  (24 nodes)
    ├── cluster_6726  (c6723, c6724, c6725)
    ├── cluster_6737  (c6734, c6735, c6736)
    └── cluster_6748  (c6745, c6746, c6747)
```

Nodes like `c4047`, `c4113`, `c4118` etc. are direct children of `cluster_4252`
but are NOT inside any leaf cluster — they sit between the inner cluster boxes.

### Phase 2 — Crossing Minimization

Within each rank, nodes are ordered top-to-bottom (in LR mode) to minimize
edge crossings.  For clustered graphs, the algorithm:

1. **Collapse** each cluster into a single skeleton node
2. Run median/transpose sweeps on the collapsed graph
3. **Expand** each cluster, running local mincross within it

For example, at rank 3 the mincross decides the top-to-bottom order is:
`c4115, c4047, c4141`.  This order minimizes crossings with ranks 2 and 4.

### Phase 3 — Coordinate Assignment (the hard part)

This is where cluster containment is enforced.  Graphviz builds an
**auxiliary constraint graph** and solves it with network simplex.

#### Step 1: Y coordinates

Each rank gets a Y coordinate based on the tallest node in that rank
plus `ranksep`.  For `aa1332.dot` (LR mode, so Y is the rank axis):

```
Rank 0 at Y=0
Rank 1 at Y = 0 + max_half_height(rank0) + ranksep + max_half_height(rank1)
Rank 2 at Y = ...
```

The tallest node in rank 3 is `c4047` (148pt), so ranks 3-4 are spaced
further apart than ranks 0-1 (where the tallest is 50pt).

#### Step 2: Build the auxiliary constraint graph

The auxiliary graph encodes ALL positioning constraints as directed edges
with `minlen` (minimum distance) and `weight` (importance).  Network simplex
then solves for the optimal X position of every node simultaneously.

**Five types of auxiliary edges:**

##### (a) Ordering edges — keep nodes in mincross order

For each pair of adjacent nodes in the same rank, add an edge that
enforces their left-to-right separation:

```
Rank 3:  c4115 ──(w=0, minlen=64)──> c4047 ──(w=0, minlen=99)──> c4141
         "c4115 must be at least 64pt left of c4047"
```

The minlen is `half_width(left) + half_width(right) + nodesep`:
- Between c4115 and c4047: 32 + 52 + 18 = ~102pt

Weight = 0 means "enforce this constraint but don't optimize for it."

##### (b) Edge alignment edges — straighten edges

For each real edge (e.g., `c4140 -> c4141`), create a virtual slack
node `sn` and two edges pulling tail and head toward alignment:

```
         sn
        / \
 (w=1) /   \ (w=1)
      v     v
   c4140   c4141
```

Both edges have minlen=0 (the slack node can be anywhere) and
weight = edge_weight.  This pulls connected nodes toward the same
X coordinate, straightening the edge.

##### (c) Cluster containment edges — keep nodes inside clusters

For each cluster, create two virtual boundary nodes `ln` (left) and
`rn` (right).  Then for each rank within the cluster, add edges from
`ln` to the leftmost node and from the rightmost node to `rn`:

```
cluster_4142:

    ln_4142 ──(minlen=margin+hw)──> c4137    (rank 0, leftmost)
    ln_4142 ──(minlen=margin+hw)──> c4139    (rank 1, leftmost)
    ln_4142 ──(minlen=margin+hw)──> c4140    (rank 2, leftmost)
    ln_4142 ──(minlen=margin+hw)──> c4141    (rank 3, leftmost)

    c4137 ──(minlen=margin+hw)──> rn_4142    (rank 0, rightmost)
    c4138 ──(minlen=margin+hw)──> rn_4142    (rank 1, rightmost)
    c4140 ──(minlen=margin+hw)──> rn_4142    (rank 2, rightmost)
    c4141 ──(minlen=margin+hw)──> rn_4142    (rank 3, rightmost)
```

These edges ensure no node escapes the cluster box.  Weight = 0.

##### (d) Cluster compaction edges — make clusters tight

```
    ln_4142 ──(minlen=1, weight=128)──> rn_4142
```

This edge has **high weight (128)**, which strongly pulls the cluster
boundaries together.  Network simplex will prioritize making the
cluster narrow over straightening low-weight edges.

##### (e) Hierarchy and separation edges

Parent clusters contain child clusters:
```
    ln_4144 ──(minlen=margin)──> ln_4142     "child left inside parent left"
    rn_4142 ──(minlen=margin)──> rn_4144     "child right inside parent right"
```

Sibling clusters are kept apart:
```
    rn_4142 ──(minlen=margin)──> ln_clusterc4143   "4142 left of c4143"
```

External nodes are kept outside:
```
    c4047 ──(minlen=margin+hw)──> ln_clusterc4047   (or reversed depending on order)
```

#### Step 3: Solve with Network Simplex

The auxiliary graph is now a directed graph with ~300 nodes and ~800 edges
(for aa1332.dot).  Network simplex finds the X position for every node
that minimizes:

```
    total_cost = SUM over all edges e:  weight(e) * (rank(head) - rank(tail))
```

subject to: `rank(head) - rank(tail) >= minlen(e)` for every edge.

**What the weights do:**

| Weight | Purpose | Effect |
|--------|---------|--------|
| 0 | Ordering, containment, separation | "Must satisfy but don't optimize" |
| 1 | Normal edge alignment | "Try to straighten this edge" |
| 128 | Cluster compaction | "Strongly prefer a narrow cluster" |
| 1000 | Group alignment | "These nodes MUST be aligned" |

The solver iterates (default up to `nslimit * |nodes|` iterations):
1. Build a spanning tree of the constraint graph
2. For each non-tree edge, compute the "cut value" — how much the
   solution improves by swapping it into the tree
3. Swap the edge with the most negative cut value
4. Repeat until no improving swap exists

#### Step 4: Extract coordinates

After network simplex, each node's "rank" field contains its X coordinate.
The cluster bounding boxes come from the `ln` and `rn` positions:

```
cluster_4142.left  = X(ln_4142)
cluster_4142.right = X(rn_4142)
```

### Phase 4 — Edge Routing

Edges are routed as polylines or B-splines through the gaps between nodes.
For edges that cross cluster boundaries (`ltail`/`lhead` attributes),
the edge is clipped to the cluster bounding box.

### Example: How cluster_4142 Gets Laid Out

Here is the complete flow for the five nodes in `cluster_4142`
(`c4137, c4138, c4139, c4140, c4141`):

1. **Rank assignment**: c4137 gets rank 0, c4138/c4139 get rank 1,
   c4140 gets rank 2, c4141 gets rank 3.

2. **Mincross**: Within each rank, nodes are ordered to minimize crossings
   with adjacent ranks.

3. **Auxiliary graph**: The solver creates `ln_4142` and `rn_4142` boundary
   nodes.  Containment edges pin all five nodes between them.  A compaction
   edge (weight=128) pulls `ln` and `rn` together.  Hierarchy edges nest
   `ln_4142`/`rn_4142` inside `ln_4144`/`rn_4144`.

4. **Network simplex**: Solves all constraints simultaneously.  The high-weight
   compaction edge makes cluster_4142 narrow.  The containment edges keep
   c4137..c4141 inside.  The alignment edges pull connected nodes together.

5. **Result**: cluster_4142 has a tight bounding box:
   `bb = (32, 1036) to (418, 1170)` — width 386pt, height 134pt.

### Reference Cluster Bounding Boxes

For the full `aa1332.dot`, here are the reference Graphviz bounding boxes:

```
cluster_6754:  3089 x 1432pt  (outermost)
cluster_4252:  1377 x  760pt  (largest sub-cluster)
  cluster_4117:  285 x  66pt  (3 nodes)
  cluster_4142:  386 x 134pt  (5 nodes)
  cluster_4148:  204 x  54pt  (2 nodes)
  cluster_4250:  721 x 234pt  (11 nodes)
cluster_5378:   568 x 148pt
cluster_6409:   620 x 208pt
cluster_6752:  1446 x 234pt
```

## Original Code

The original Graphviz C source is from https://gitlab.com/graphviz/graphviz/


## Related Projects

- [pictosync](https://github.com/pjm4github/pictosync) — rendering pipeline via `attribute_schema.json`
