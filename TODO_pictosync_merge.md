# Pictosync ↔ GraphvizPy Merge Plan

## Vision

Merge GraphvizPy's `cgraph` package into pictosync as the foundational data model. The cgraph `Graph`, `Node`, and `Edge` classes become the single source of truth for all diagram data, with pictosync's canvas items as views and cgraph's layout engines computing positions.

Additionally, GraphvizPy retains a standalone graphic stub (`MainGraphvisPy.py`) for validating layout engines independently of pictosync.

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                      Pictosync UI                          │
│  ┌───────────┐  ┌────────────┐  ┌───────────┐  ┌────────┐  │
│  │ Canvas    │  │ QTreeView  │  │ Property  │  │ Sim    │  │
│  │ (Scene)   │  │ (Hierarchy)│  │  Panel    │  │ Panel  │  │
│  └─────┬─────┘  └─────┬──────┘  └─────┬─────┘  └───┬────┘  │
├────────┴──────────────┴───────────────┴────────────┴───────┤
│                     Adapter Layer                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ GraphAdapter │  │ GraphTree    │  │ FileStore        │  │
│  │ canvas↔cgraph│  │ Model        │  │ subgraph→folder  │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────────┘  │
├─────────┴─────────────────┴─────────────────┴──────────────┤
│                      cgraph Layer                          │
│  Graph (NodeMixin + EdgeMixin + SubgraphMixin + ...)       │
│  Node → SimNode (with 4-phase execution protocol)          │
│  Edge (carries signal values between nodes)                │
│  Subgraph = Group (compound node with nested graph)        │
├────────────────────────────────────────────────────────────┤
│                     Engine Layer                           │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌─────────┐   │
│  │  dot   │ │ neato  │ │ circo  │ │  MNAM  │ │Discrete │   │
│  │ layout │ │ layout │ │ layout │ │ matrix │ │time sim │   │
│  └────────┘ └────────┘ └────────┘ └────────┘ └─────────┘   │
└────────────────────────────────────────────────────────────┘
```

## Core Principle

**cgraph is the single source of truth.** Every pictosync canvas item has a backing cgraph Node or Edge. When a user interacts with the canvas, the adapter updates cgraph. When an engine computes layout or simulation results, cgraph is updated first, then the adapter pushes changes to the canvas.

```
User drags rect → Canvas item moves → Adapter updates Node.pos → Done

Layout button → DotLayout(graph).layout() → Adapter repositions canvas items

Simulation step → Engine walks graph → Node states update → Adapter refreshes UI
```

---

## Phase 1: Install graphvizpy as a pip dependency

**Goal:** Make cgraph available to pictosync without duplicating code.

**Why not copy files?** Copying `pycode/cgraph/` into pictosync creates two diverging codebases. Instead, GraphvizPy is a pip-installable package that pictosync depends on.

**GraphvizPy `pyproject.toml`** defines the package:
```toml
[project]
name = "graphvizpy"
version = "0.1.0"
dependencies = ["antlr4-python3-runtime~=4.13.0", "numpy~=2.2.1", "scipy~=1.14.1"]

[project.optional-dependencies]
gui = ["PyQt6~=6.7.0", "pyqtgraph"]

[tool.setuptools.packages.find]
include = ["pycode*"]
```

**During development** — editable install (symlink, no copy):
```bash
cd C:\Users\pmora\OneDrive\Documents\Git\GitHub\pictosync
pip install -e C:\Users\pmora\OneDrive\Documents\Git\GitHub\GraphvizPy
```
Changes in GraphvizPy are immediately available in pictosync. Each repo keeps its own git history — the editable install is a local venv link, not tracked by git.

**Pictosync `pyproject.toml`** — graphvizpy as an optional dependency:
```toml
[project]
name = "pictosync"
dependencies = [
    "PyQt6~=6.7.0",
    # ... core pictosync deps only
]

[project.optional-dependencies]
graph = ["graphvizpy>=0.1.0"]          # core + layout engines
simulation = ["graphvizpy>=0.1.0", "numpy", "scipy"]  # + simulation
all = ["graphvizpy[gui,simulation]"]
```

**User install scenarios:**
| Command | What they get |
|---------|--------------|
| `pip install pictosync` | Canvas + SVG nodes only |
| `pip install pictosync[graph]` | + cgraph, layout, DOT import/export |
| `pip install pictosync[simulation]` | + discrete-time sim, MNAM |
| `pip install pictosync[all]` | Everything |

Until graphvizpy is published to PyPI, the `[graph]` extra won't resolve for outside users — they get base pictosync. When ready, publish graphvizpy and the extras just work.

**Guarding imports in pictosync:**

```python
try:
    from gvpy.core.graph import Graph
    from gvpy.dot.dot_layout import DotLayout

    HAS_CGRAPH = True
except ImportError:
    HAS_CGRAPH = False
```
Disable layout/simulation menu items when `HAS_CGRAPH is False`.

**Verification:**

```python
from gvpy.core import Graph, Node, Edge
from gvpy.dot.dot_reader import read_dot, read_dot_file
from gvpy.dot.dot_layout import DotLayout
```

---

## Phase 2: GraphAdapter — Bridge canvas ↔ cgraph

**New file:** `pictosync/canvas/graph_adapter.py`

The adapter maintains a bidirectional mapping between pictosync annotation IDs and cgraph node/edge names.

```python
class GraphAdapter:
    """Bridges pictosync canvas items with a core Graph."""
    
    def __init__(self, scene: AnnotatorScene):
        self.scene = scene
        self.graph = Graph("document", directed=True)
        self.graph.method_init()
        self._ann_to_node: dict[str, Node] = {}   # ann_id → Node
        self._ann_to_edge: dict[str, Edge] = {}   # ann_id → Edge
    
    # ── Canvas → Graph sync ──────────────────────
    
    def on_item_added(self, item):
        """Called when user creates an item on canvas."""
        if item.kind in SHAPE_KINDS:
            node = self.graph.add_node(item.ann_id)
            node.shape = KIND_TO_DOT_SHAPE.get(item.kind, "ellipse")
            node.label = item.meta.label or item.ann_id
            node.set_attr("x", str(item.x()))
            node.set_attr("y", str(item.y()))
            self._ann_to_node[item.ann_id] = node
        elif item.kind in LINE_KINDS:
            # Determine tail/head from port connections
            tail_id, head_id = self._resolve_endpoints(item)
            if tail_id and head_id:
                edge = self.graph.add_edge(tail_id, head_id)
                edge.label = item.meta.label or ""
                self._ann_to_edge[item.ann_id] = edge
    
    def on_item_changed(self, item):
        """Called when user modifies an item."""
        node = self._ann_to_node.get(item.ann_id)
        if node:
            node.label = item.meta.label
            node.set_attr("x", str(item.x()))
            node.set_attr("y", str(item.y()))
    
    def on_item_deleted(self, item):
        """Called when user deletes an item."""
        if item.ann_id in self._ann_to_node:
            self.graph.delete_node(self._ann_to_node.pop(item.ann_id))
        elif item.ann_id in self._ann_to_edge:
            self.graph.delete_edge(self._ann_to_edge.pop(item.ann_id))
    
    # ── Graph → Canvas sync ──────────────────────
    
    def apply_layout(self, engine="dot"):
        """Run layout engine and reposition all canvas items."""
        result = DotLayout(self.graph).layout()
        for node_data in result["nodes"]:
            item = self._find_canvas_item(node_data["name"])
            if item:
                item.setPos(node_data["x"], node_data["y"])
    
    # ── Group/Ungroup = Subgraph ─────────────────
    
    def group_items(self, ann_ids: list[str], group_name: str):
        """Group items into a subgraph (compound node)."""
        subg = self.graph.create_subgraph(group_name)
        for ann_id in ann_ids:
            if ann_id in self._ann_to_node:
                subg.add_node(ann_id)
    
    def ungroup(self, group_name: str):
        """Dissolve a subgraph back into the parent graph."""
        self.graph.delete_subgraph(
            self.graph.subgraphs.get(group_name))
```

**Shape mapping:**
```python
SHAPE_KINDS = {"rect", "roundedrect", "ellipse", "hexagon", "cylinder",
               "blockarrow", "polygon", "isocube", "seqblock", "text"}
LINE_KINDS = {"line", "curve", "orthocurve"}

KIND_TO_DOT_SHAPE = {
    "rect": "box", "roundedrect": "Mrecord", "ellipse": "ellipse",
    "hexagon": "hexagon", "cylinder": "cylinder", "text": "plaintext",
    "polygon": "polygon",
}

DOT_SHAPE_TO_KIND = {v: k for k, v in KIND_TO_DOT_SHAPE.items()}
# Plus Graphviz-specific additions:
DOT_SHAPE_TO_KIND.update({
    "box": "rect", "circle": "ellipse", "diamond": "polygon",
    "triangle": "polygon", "record": "rect", "point": "ellipse",
    "doublecircle": "ellipse", "octagon": "polygon",
})
```

---

## Phase 3: QTreeView — Graph hierarchy browser

**New file:** `pictosync/canvas/graph_tree_model.py`

```python
class GraphTreeModel(QStandardItemModel):
    """QTreeView model backed by core subgraph hierarchy.
    
    Mirrors the graph structure: root graph at top, subgraphs as
    expandable folders, nodes as leaf items, edges as children of
    their tail node.
    """
    
    def __init__(self, graph: Graph):
        super().__init__()
        self.graph = graph
        self._node_items: dict[str, QStandardItem] = {}
        self.rebuild()
        
        # Auto-update on graph changes
        graph.method_update(GraphEvent.NODE_ADDED, 
                           lambda n: self.rebuild(), 'add')
        graph.method_update(GraphEvent.SUBGRAPH_ADDED,
                           lambda s: self.rebuild(), 'add')
    
    def rebuild(self):
        self.clear()
        self.setHorizontalHeaderLabels(["Graph Structure"])
        root_item = QStandardItem(f"📊 {self.graph.name}")
        self.appendRow(root_item)
        self._build_subtree(root_item, self.graph)
    
    def _build_subtree(self, parent_item, graph):
        # Subgraphs first (as folders)
        for name, subg in graph.subgraphs.items():
            icon = "📁" if name.startswith("cluster") else "📂"
            subg_item = QStandardItem(f"{icon} {name}")
            parent_item.appendRow(subg_item)
            self._build_subtree(subg_item, subg)
        
        # Then nodes
        for name, node in graph.nodes.items():
            shape_icon = {"box": "▭", "ellipse": "⬭", "diamond": "◆"
                         }.get(node.shape, "●")
            node_item = QStandardItem(f"{shape_icon} {node.label}")
            parent_item.appendRow(node_item)
            self._node_items[name] = node_item
```

**File persistence:** Each subgraph can be saved as a separate JSON file in a folder hierarchy:
```
project/
├── root.json           # Root graph with top-level nodes
├── cluster_ui/
│   └── graph.json      # Subgraph with UI component nodes
├── cluster_api/
│   └── graph.json      # Subgraph with API component nodes
└── cluster_db/
    └── graph.json      # Subgraph with database nodes
```

---

## Phase 4: Layout integration

**Add to pictosync main.py:**
- Menu: Layout → Hierarchical (dot)
- Menu: Layout → Force-directed (neato) [future]
- Menu: Layout → Circular (circo) [future]
- Menu: Layout → Radial (twopi) [future]

```python
def on_layout_dot(self):
    """Run dot hierarchical layout on the current graph."""
    self.graph_adapter.apply_layout(engine="dot")
    self.scene.update()
```

---

## Phase 5: DOT import/export

**Add to pictosync File menu:**
- File → Import DOT (.gv, .dot)
- File → Export DOT

```python
def import_dot(self, filepath):
    """Parse DOT file and create canvas items."""
    graph = read_dot_file(filepath)
    result = DotLayout(graph).layout()
    for node_data in result["nodes"]:
        kind = DOT_SHAPE_TO_KIND.get(node_data.get("shape", "ellipse"), "ellipse")
        item = self.scene.create_item(kind, x=node_data["x"], y=node_data["y"],
                                       w=node_data["width"], h=node_data["height"])
        item.meta.label = node_data.get("label", node_data["name"])
        # ... set style from DOT attributes

def export_dot(self, filepath):
    """Serialize the current graph to DOT format."""
    # Walk the graph and generate DOT text
    lines = [f'digraph {self.graph_adapter.graph.name} {{']
    for name, node in self.graph_adapter.graph.nodes.items():
        attrs = ', '.join(f'{k}="{v}"' for k, v in node.attributes.items() if v)
        lines.append(f'    {name} [{attrs}];')
    for key, edge in self.graph_adapter.graph.edges.items():
        tail, head, name = key
        lines.append(f'    {tail} -> {head};')
    lines.append('}')
    Path(filepath).write_text('\n'.join(lines))
```

---

## Phase 6: SimNode — Simulation-capable nodes

**New file:** `pictosync/simulation/sim_node.py`

```python
from gvpy.core.node import Node


class SimNode(Node):
    """Node with discrete-time simulation support.
    
    Subclass this for domain-specific behavior (logic gates,
    state machines, process blocks, etc.).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.state: dict = {}  # persistent across steps
        self.inputs: dict = {}  # values from in-edges (read in phase A)
        self.outputs: dict = {}  # values to out-edges (written in phase C)

    def phase_a_read_inputs(self):
        """(a) Collect input values from incoming edges."""
        self.inputs.clear()
        for edge in self.inedges:
            port = edge.tailport or "default"
            val = edge.attributes.get("_signal")
            if val is not None:
                self.inputs[port] = val

    def phase_b_compute(self):
        """(b) Internal logic — override in domain subclass."""
        pass

    def phase_c_write_outputs(self):
        """(c) Push output values to outgoing edges."""
        for edge in self.outedges:
            port = edge.headport or "default"
            if port in self.outputs:
                edge.set_attr("_signal", str(self.outputs[port]))

    def phase_d_topology(self):
        """(d) Topology changes — override in domain subclass."""
        pass
```

**Example domain subclass:**
```python
class AndGate(SimNode):
    """2-input AND gate."""
    
    def phase_b_compute(self):
        a = self.inputs.get("in1", "0")
        b = self.inputs.get("in2", "0")
        self.outputs["out"] = "1" if (a == "1" and b == "1") else "0"

class Counter(SimNode):
    """Simple counter that increments each step."""
    
    def phase_b_compute(self):
        count = int(self.state.get("count", "0"))
        if self.inputs.get("reset") == "1":
            count = 0
        elif self.inputs.get("enable", "1") == "1":
            count += 1
        self.state["count"] = str(count)
        self.outputs["value"] = str(count)
```

---

## Phase 7: Discrete-time simulation engine

**New file:** `pictosync/simulation/engine.py`

```python
class DiscreteTimeSimulator:
    """Runs 4-phase simulation on a core Graph containing SimNodes."""
    
    def __init__(self, graph: Graph):
        self.graph = graph
        self.time_step = 0
        self.history: list[dict] = []  # optional state recording
    
    @property
    def sim_nodes(self) -> list[SimNode]:
        return [n for n in self.graph.nodes.values() 
                if isinstance(n, SimNode)]
    
    def step(self):
        """Execute one discrete time step (all 4 phases)."""
        nodes = self.sim_nodes
        
        for node in nodes:
            node.phase_a_read_inputs()
        for node in nodes:
            node.phase_b_compute()
        for node in nodes:
            node.phase_c_write_outputs()
        for node in nodes:
            node.phase_d_topology()
        
        self.time_step += 1
        self._record_state(nodes)
    
    def run(self, steps: int):
        """Run multiple simulation steps."""
        for _ in range(steps):
            self.step()
    
    def reset(self):
        """Reset all node states and time."""
        for node in self.sim_nodes:
            node.state.clear()
            node.inputs.clear()
            node.outputs.clear()
        self.time_step = 0
        self.history.clear()
    
    def _record_state(self, nodes):
        """Record current state for playback/analysis."""
        snapshot = {
            "time": self.time_step,
            "nodes": {n.name: dict(n.state) for n in nodes},
            "edges": {k: e.attributes.get("_signal", "")
                      for k, e in self.graph.edges.items()},
        }
        self.history.append(snapshot)
```

---

## Phase 8: MNAM matrix builder

**New file:** `pictosync/simulation/mnam.py`

```python
import numpy as np
from gvpy.core import Graph


class MNAMBuilder:
    """Build Modified Nodal Admittance Matrix from core topology.
    
    Each node becomes a row/column. Each edge contributes admittance
    values to the matrix based on its 'admittance' or 'weight' attribute.
    """

    def __init__(self, graph: Graph):
        self.graph = graph

    def build(self) -> tuple[np.ndarray, list[str]]:
        """Returns (Y_matrix, node_names)."""
        names = list(self.graph.nodes.keys())
        n = len(names)
        idx = {name: i for i, name in enumerate(names)}

        Y = np.zeros((n, n), dtype=complex)

        for key, edge in self.graph.edges.items():
            tail, head, _ = key
            if tail not in idx or head not in idx:
                continue
            # Admittance from edge attribute (default 1.0)
            y_str = edge.attributes.get("admittance") or
            edge.attributes.get("weight", "1")
        try:
            y = complex(y_str)
        except ValueError:
            y = 1.0

        i, j = idx[tail], idx[head]
        Y[i, j] -= y
        Y[j, i] -= y
        Y[i, i] += y
        Y[j, j] += y

    return Y, names


def solve_voltages(self, current_sources: dict[str, complex]) -> dict[str, complex]:
    """Given current injections at nodes, solve for node voltages.
    
    Uses Y * V = I  →  V = Y^-1 * I
    """
    Y, names = self.build()
    n = len(names)
    I = np.zeros(n, dtype=complex)
    for name, current in current_sources.items():
        if name in {n: i for i, n in enumerate(names)}:
            I[{n: i for i, n in enumerate(names)}[name]] = current

    # Ground reference: remove last row/col (or use pseudoinverse)
    if n > 1:
        Y_reduced = Y[:-1, :-1]
        I_reduced = I[:-1]
        V_reduced = np.linalg.solve(Y_reduced, I_reduced)
        V = np.append(V_reduced, 0.0)  # ground node = 0V
    else:
        V = np.array([0.0])

    return {names[i]: V[i] for i in range(n)}
```

---

## GraphvizPy Layout Validation Stub

**Goal:** Keep `MainGraphvisPy.py` as a standalone tool for testing and validating all layout engines (dot, neato, circo, fdp, sfdp, twopi) independently of pictosync.

**Refactoring plan for MainGraphvisPy.py:**
- Wire cgraph Graph/Node/Edge as backing model (see `TODO_main_gui.md`)
- Add "Layout" menu with all 6 engine options
- Each engine runs on the cgraph graph and repositions QGraphicsItems
- Engines that aren't implemented yet show "(not implemented)" but the menu entry exists
- This validates the cgraph → layout → visual pipeline end-to-end

**Layout engine stubs in pycode/:**
```
pycode/
├── dot/dot_layout.py      # IMPLEMENTED — hierarchical
├── neato/__init__.py       # STUB — force-directed (future)
├── circo/__init__.py       # STUB — circular (future)
├── fdp/__init__.py         # STUB — force-directed placement (future)
├── sfdp/__init__.py        # STUB — multiscale force-directed (future)
└── twopi/__init__.py       # STUB — radial (future)
```

Each stub would have:
```python
# gvpycode/neato/__init__.py
class NeatoLayout:
    """Force-directed layout engine (not yet implemented)."""
    def __init__(self, graph):
        self.graph = graph
    def layout(self) -> dict:
        raise NotImplementedError("Neato layout engine not yet implemented")
```

**MainGraphvisPy.py Layout menu:**
```python
layout_menu = self.menuBar().addMenu("Layout")

dot_action = QAction("Hierarchical (dot)", self)
dot_action.triggered.connect(lambda: self.run_layout("dot"))
layout_menu.addAction(dot_action)

neato_action = QAction("Force-directed (neato) [future]", self)
neato_action.triggered.connect(lambda: self.run_layout("neato"))
layout_menu.addAction(neato_action)

# ... same for circo, fdp, sfdp, twopi
```

---

## Implementation Order

| Phase | What | Where | Depends On |
|-------|------|-------|------------|
| **1** | `pip install -e graphvizpy` | pictosync venv | `pyproject.toml` |
| **2** | GraphAdapter (canvas ↔ cgraph) | pictosync/canvas/ | Phase 1 |
| **3** | QTreeView hierarchy browser | pictosync/canvas/ | Phase 2 |
| **4** | Layout button (dot) | pictosync/main.py | Phase 2 |
| **5** | DOT import/export | pictosync/main.py | Phase 2 |
| **6** | Group/Ungroup = Subgraph | pictosync/canvas/ | Phase 2+3 |
| **7** | SimNode subclass | pictosync/simulation/ | Phase 1 |
| **8** | Discrete-time engine | pictosync/simulation/ | Phase 7 |
| **9** | MNAM matrix builder | pictosync/simulation/ | Phase 1 |
| **10** | MainGraphvisPy cgraph integration | GraphvizPy/ | Phase 1 |
| **11** | Layout engine stubs (neato, circo, etc.) | GraphvizPy/pycode/ | Phase 10 |

---

## Key Design Decisions

1. **cgraph is the single source of truth** — canvas items are views, engines are processors
2. **graphvizpy is a pip package, not copied code** — one repo, editable install into pictosync's venv; optional dependency so pictosync works standalone
3. **Adapter pattern, not inheritance** — canvas items don't subclass Node; an adapter syncs them
3. **SimNode extends Node** — simulation behavior added via subclass, not monkey-patching
4. **Subgraphs = Groups** — pictosync groups map directly to cgraph subgraphs
5. **File-per-subgraph persistence** — each subgraph can be its own JSON file in a folder
6. **Layout engines are pluggable** — dot today, neato/circo/fdp/sfdp/twopi tomorrow
7. **Edges carry signals** — edge attributes transport values between SimNodes
8. **MNAM from topology** — matrix extracted directly from cgraph adjacency structure
9. **GraphvizPy stays standalone** — MainGraphvisPy validates layouts without pictosync
10. **No breaking changes** — pictosync's existing annotation_schema.json and canvas items are unchanged
