# MainGraphvisPy.py — Refactoring to Use cgraph Package

## Goal

Refactor `MainGraphvisPy.py` to use the `pycode.cgraph` Graph, Node, and Edge classes as its backing data model instead of standalone QGraphicsItem subclasses. This validates the cgraph class structure through interactive GUI manipulation and prepares the codebase for eventual merge into [pictosync](https://github.com/pjm4github/pictosync).

## Current State

`MainGraphvisPy.py` (v1.7.12) has its own inline classes:
- `NodeItem(QGraphicsRectItem)` — draggable rectangle with connectors
- `ConnectorItem(QGraphicsEllipseItem)` — connection point on node boundary
- `IOConnectorItem(QGraphicsPolygonItem)` — standalone diamond connector
- `EdgeItem(QGraphicsLineItem)` — line between connectors
- `GraphicsScene(QGraphicsScene)` — drawing canvas with modes (draw_node, draw_edge, select)

These classes have **no connection** to `pycode.cgraph.Graph`, `Node`, or `Edge`. The scene manages its own data structures for nodes, edges, and connectors.

## Refactoring Plan

### Phase 1: Backing Model Integration

- [ ] Create a `pycode.cgraph.Graph` instance as the scene's backing model
- [ ] When user creates a node via GUI → call `graph.add_node(name)` to create a cgraph Node
- [ ] When user draws an edge via GUI → call `graph.add_edge(tail, head)` to create a cgraph Edge
- [ ] When user deletes a node/edge → call `graph.delete_node()` / `graph.delete_edge()`
- [ ] Store the cgraph Node reference on each `NodeItem` (e.g. `self.cgraph_node = graph.add_node(...)`)
- [ ] Store the cgraph Edge reference on each `EdgeItem`
- [ ] Sync attributes: when user changes node appearance → update `cgraph_node.agset(attr, value)`

### Phase 2: Scene Save/Load via cgraph

- [ ] Replace the custom JSON save/load (`saveScene`/`loadScene`) with DOT format
- [ ] Save: serialize the backing `Graph` to DOT text (need `agwrite` or DOT serializer)
- [ ] Load: use `pycode.dot.read_dot_file()` to parse DOT into Graph, then create GUI items from it
- [ ] This validates the round-trip: GUI → cgraph → DOT → cgraph → GUI

### Phase 3: Layout Integration

- [ ] Add "Auto Layout" button/menu that runs `DotLayout(graph).layout()` on the backing graph
- [ ] After layout, update all `NodeItem` positions from the computed coordinates
- [ ] After layout, update all `EdgeItem` routing from the computed edge points
- [ ] Support layout attributes (rankdir, ranksep, nodesep) via the preferences dialog

### Phase 4: Attribute Sync

- [ ] Node attributes (shape, color, fillcolor, style, fontname, fontsize, label) stored on cgraph Node
- [ ] Edge attributes (color, style, arrowhead, arrowtail, label, weight, minlen) stored on cgraph Edge
- [ ] Graph attributes (rankdir, splines, bgcolor) stored on cgraph Graph
- [ ] Subgraph/cluster support: user can group nodes into subgraphs
- [ ] Node appearance dialog reads/writes cgraph attributes

### Phase 5: Pictosync Preparation

- [ ] Align the `GraphicsScene` architecture with pictosync's `QGraphicsScene`-based canvas
- [ ] Use pictosync's `SVGNodeRegistry` pattern for node shape rendering
- [ ] Ensure the cgraph model can be serialized to pictosync's `attribute_schema.json` format
- [ ] Ensure edge routing is compatible with pictosync's edge rendering pipeline
- [ ] Use snake_case for new internal identifiers (pictosync convention)

## Design Constraints

- The cgraph `Graph` object is the **single source of truth** — GUI items are views of cgraph data
- All user operations (add/delete/modify) go through the cgraph API first, then update the GUI
- The GUI should never hold state that isn't reflected in the cgraph model
- The cgraph callback system (`GraphEvent.NODE_ADDED`, `EDGE_DELETED`, etc.) can drive GUI updates

## Callback Architecture

```
User clicks "draw node"
  → GraphicsScene.mousePressEvent()
    → self.graph.add_node(name)           # cgraph API
      → GraphEvent.NODE_ADDED callback     # cgraph fires event
        → scene.on_node_added(node)        # GUI creates NodeItem
          → NodeItem positioned at click point
```

This callback-driven architecture ensures cgraph and GUI stay in sync, and matches pictosync's event-driven pattern.

## Files Affected

| File | Changes |
|---|---|
| `MainGraphvisPy.py` | Major refactoring: integrate cgraph backing model |
| `pycode/cgraph/graph.py` | May need DOT serialization (`agwrite`) |
| `pycode/cgraph/node.py` | May need position attributes (x, y) for GUI sync |
| `pycode/cgraph/edge.py` | May need routing attributes for GUI sync |

## Testing Strategy

Manual GUI testing through interactive manipulation:
1. Create nodes → verify they appear in `graph.nodes`
2. Draw edges → verify they appear in `graph.edges`
3. Delete items → verify removal from cgraph
4. Save as DOT → verify valid DOT output
5. Load DOT file → verify GUI recreation
6. Run auto-layout → verify positions update
7. Modify attributes via dialog → verify cgraph sync
8. Round-trip: create → save → load → verify identical graph
