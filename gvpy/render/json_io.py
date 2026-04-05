"""
JSON graph format reader/writer — Graphviz-compatible JSON interchange.

Supports two JSON variants matching Graphviz ``-Tjson`` and ``-Tjson0``:

- **json0**: Structural data only — nodes, edges, subgraphs, and their
  attributes.  No layout coordinates or drawing operations.
- **json**: Structural data plus layout coordinates (``pos``, ``width``,
  ``height``, ``bb``) when available.  Drawing operations (``_draw_``,
  ``_ldraw_``) are included from layout results when provided.

File extensions: ``.json``

JSON Structure (Graphviz-compatible)::

    {
        "name": "G",
        "directed": true,
        "strict": false,
        "_subgraph_cnt": 2,
        "objects": [ ... ],     // subgraphs/clusters
        "nodes": [ ... ],       // node objects with _gvid
        "edges": [ ... ]        // edge objects with tail/head as _gvid indices
    }
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Union

if TYPE_CHECKING:
    from gvpy.core.graph import Graph


# ── Writer ──────────────────────────────────────────────────────


def _node_attrs(node) -> dict[str, str]:
    """Collect non-empty, non-internal attributes from a node."""
    return {k: v for k, v in node.attributes.items()
            if v is not None and v != "" and not k.startswith("_")}


def _edge_attrs(edge) -> dict[str, str]:
    """Collect non-empty, non-internal attributes from an edge."""
    return {k: v for k, v in edge.attributes.items()
            if v is not None and v != "" and not k.startswith("_")}


def _collect_subgraphs(graph: "Graph", objects: list, node_index: dict,
                       gvid_counter: list[int]):
    """Recursively collect subgraph objects."""
    for name, sub in graph.subgraphs.items():
        obj: dict = {
            "_gvid": gvid_counter[0],
            "name": name,
            "nodes": [node_index[n] for n in sub.nodes if n in node_index],
            "edges": [],
        }
        gvid_counter[0] += 1

        # Subgraph-level attributes (from attr_record for subgraph-local attrs)
        if hasattr(sub, "attr_record"):
            for k, v in sub.attr_record.items():
                if v is not None and v != "" and not k.startswith("_"):
                    obj[k] = v

        # Edges within this subgraph
        for key, edge in sub.edges.items():
            tail_name = edge.tail.name
            head_name = edge.head.name
            if tail_name in node_index and head_name in node_index:
                obj["edges"].append({
                    "tail": node_index[tail_name],
                    "head": node_index[head_name],
                })

        objects.append(obj)

        # Recurse into nested subgraphs
        _collect_subgraphs(sub, objects, node_index, gvid_counter)


def write_json(graph: "Graph", layout_result: dict | None = None,
               include_draw_ops: bool = True) -> str:
    """Serialize a Graph to Graphviz-compatible JSON format.

    Parameters
    ----------
    graph : Graph
        The graph to serialize.
    layout_result : dict, optional
        Layout result from ``DotLayout.layout()``.  When provided and
        ``include_draw_ops`` is True, layout coordinates and drawing
        operations are included (``-Tjson`` mode).  When None or
        ``include_draw_ops`` is False, only structural data is written
        (``-Tjson0`` mode).
    include_draw_ops : bool
        If True (default), include layout data when ``layout_result``
        is provided.  Set to False for ``-Tjson0`` output.

    Returns
    -------
    str
        JSON text.
    """
    # Build node list with _gvid indices
    nodes_json = []
    node_index: dict[str, int] = {}  # node name → _gvid

    # Build layout lookup if available
    layout_nodes = {}
    layout_edges = []
    if layout_result and include_draw_ops:
        for ln in layout_result.get("nodes", []):
            layout_nodes[ln["name"]] = ln
        layout_edges = layout_result.get("edges", [])

    for i, (name, node) in enumerate(graph.nodes.items()):
        node_index[name] = i
        entry: dict = {
            "_gvid": i,
            "name": name,
        }
        # User-set attributes
        entry.update(_node_attrs(node))

        # Label defaults to name if not set
        if "label" not in entry:
            entry["label"] = name

        # Layout data
        if name in layout_nodes:
            ln = layout_nodes[name]
            entry["pos"] = f"{ln['x']},{ln['y']}"
            entry["width"] = str(round(ln["width"] / 72.0, 4))
            entry["height"] = str(round(ln["height"] / 72.0, 4))
            # Include shape from layout if not in attributes
            if "shape" not in entry and "shape" in ln:
                entry["shape"] = ln["shape"]

        nodes_json.append(entry)

    # Build edge list
    edges_json = []
    edge_layout_idx = 0
    for i, (key, edge) in enumerate(graph.edges.items()):
        tail_name = edge.tail.name
        head_name = edge.head.name
        entry: dict = {
            "_gvid": i,
            "tail": node_index.get(tail_name, 0),
            "head": node_index.get(head_name, 0),
        }
        # User-set attributes
        entry.update(_edge_attrs(edge))

        # Layout data
        if edge_layout_idx < len(layout_edges):
            le = layout_edges[edge_layout_idx]
            if le.get("tail") == tail_name and le.get("head") == head_name:
                points = le.get("points", [])
                if points:
                    pos_parts = []
                    for j, pt in enumerate(points):
                        if j == 0:
                            pos_parts.append(f"s,{pt[0]},{pt[1]}")
                        elif j == len(points) - 1:
                            pos_parts.append(f"e,{pt[0]},{pt[1]}")
                        else:
                            pos_parts.append(f"{pt[0]},{pt[1]}")
                    entry["pos"] = " ".join(pos_parts)
                edge_layout_idx += 1

        edges_json.append(entry)

    # Build subgraph objects
    objects: list[dict] = []
    gvid_counter = [0]
    _collect_subgraphs(graph, objects, node_index, gvid_counter)

    # Top-level JSON
    result: dict = {
        "name": graph.name,
        "directed": graph.directed,
        "strict": graph.strict,
        "_subgraph_cnt": len(objects),
    }

    # Graph-level attributes
    if hasattr(graph, "attr_dict_g"):
        for k, v in graph.attr_dict_g.items():
            if v is not None and v != "":
                result[k] = v

    # Layout bounding box
    if layout_result and include_draw_ops:
        graph_meta = layout_result.get("graph", {})
        if "bb" in graph_meta:
            bb = graph_meta["bb"]
            result["bb"] = f"{bb[0]},{bb[1]},{bb[2]},{bb[3]}"

    result["objects"] = objects
    result["nodes"] = nodes_json
    result["edges"] = edges_json

    return json.dumps(result, indent=2, ensure_ascii=False)


def write_json0(graph: "Graph") -> str:
    """Serialize a Graph to Graphviz json0 format (structural only, no layout)."""
    return write_json(graph, layout_result=None, include_draw_ops=False)


def write_json_file(graph: "Graph", filepath: str,
                    layout_result: dict | None = None,
                    include_draw_ops: bool = True) -> None:
    """Write a Graph to a JSON file."""
    text = write_json(graph, layout_result, include_draw_ops)
    Path(filepath).write_text(text, encoding="utf-8")


# ── Reader ──────────────────────────────────────────────────────


def read_json(text: str) -> "Graph":
    """Parse Graphviz-compatible JSON text into a Graph object.

    Accepts both ``-Tjson`` and ``-Tjson0`` format.

    Parameters
    ----------
    text : str
        JSON text to parse.

    Returns
    -------
    Graph
        A fully constructed Graph object.
    """
    from gvpy.core.graph import Graph

    data = json.loads(text)

    name = data.get("name", "G")
    directed = data.get("directed", True)
    strict = data.get("strict", False)

    g = Graph(name, directed=directed, strict=strict)
    g.method_init()

    # Graph-level attributes
    skip_keys = {"name", "directed", "strict", "_subgraph_cnt",
                 "objects", "nodes", "edges", "bb"}
    for k, v in data.items():
        if k not in skip_keys and isinstance(v, str):
            g.set_graph_attr(k, v)
    if "bb" in data:
        g.set_graph_attr("bb", str(data["bb"]))

    # Node name lookup: _gvid → name
    gvid_to_name: dict[int, str] = {}

    # Create nodes
    for node_data in data.get("nodes", []):
        node_name = node_data.get("name", str(node_data.get("_gvid", "")))
        gvid = node_data.get("_gvid", 0)
        gvid_to_name[gvid] = node_name

        node = g.add_node(node_name)
        skip_node_keys = {"_gvid", "name"}
        for k, v in node_data.items():
            if k not in skip_node_keys and isinstance(v, str):
                node.agset(k, v)

    # Create subgraphs from objects
    for obj in data.get("objects", []):
        sub_name = obj.get("name", f"subgraph_{obj.get('_gvid', 0)}")
        sub = g.create_subgraph(sub_name)

        # Subgraph attributes (stored in attr_record for subgraph-local attrs)
        skip_obj_keys = {"_gvid", "name", "nodes", "edges"}
        for k, v in obj.items():
            if k not in skip_obj_keys and isinstance(v, str):
                sub.attr_record[k] = v

        # Add nodes to subgraph by _gvid index
        for node_gvid in obj.get("nodes", []):
            node_name = gvid_to_name.get(node_gvid)
            if node_name and node_name in g.nodes:
                sub.add_node(node_name)

    # Create edges
    for edge_data in data.get("edges", []):
        tail_gvid = edge_data.get("tail", 0)
        head_gvid = edge_data.get("head", 0)
        tail_name = gvid_to_name.get(tail_gvid)
        head_name = gvid_to_name.get(head_gvid)

        if tail_name and head_name:
            edge = g.add_edge(tail_name, head_name)
            skip_edge_keys = {"_gvid", "tail", "head"}
            for k, v in edge_data.items():
                if k not in skip_edge_keys and isinstance(v, str):
                    edge.agset(k, v)

    return g


def read_json_file(filepath: Union[str, Path]) -> "Graph":
    """Read a Graphviz JSON file and parse it into a Graph object."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8")
    return read_json(text)
