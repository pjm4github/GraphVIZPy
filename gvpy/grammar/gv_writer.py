"""
GV/DOT language writer — serialize Graph objects back to DOT format.

Produces valid DOT text that can be parsed by Graphviz or ``read_gv()``.
Supports digraph/graph, strict mode, subgraphs, clusters, and all
node/edge/graph attributes.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from gvpy.core.graph import Graph
    from gvpy.core.node import Node
    from gvpy.core.edge import Edge


def _needs_quoting(s: str) -> bool:
    """Return True if an ID needs double-quoting in DOT output."""
    if not s:
        return True
    # HTML labels
    if s.startswith("<") and s.endswith(">"):
        return False
    # Keywords that must be quoted if used as IDs
    keywords = {"graph", "digraph", "subgraph", "node", "edge", "strict"}
    if s.lower() in keywords:
        return True
    # Pure numeric (int or float) is fine unquoted
    try:
        float(s)
        return False
    except ValueError:
        pass
    # Bare identifiers: [a-zA-Z_\x80-\xff][a-zA-Z0-9_\x80-\xff]*
    if s[0].isalpha() or s[0] == "_" or ord(s[0]) >= 0x80:
        return not all(
            c.isalnum() or c == "_" or ord(c) >= 0x80 for c in s
        )
    return True


def _quote(s: str) -> str:
    """Quote a DOT identifier if necessary."""
    if _needs_quoting(s):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return s


def _format_attrs(attrs: dict[str, str]) -> str:
    """Format an attribute dict as a DOT attribute list: [key=val, ...]."""
    if not attrs:
        return ""
    pairs = []
    for k, v in attrs.items():
        if v is None or k.startswith("_"):
            continue
        pairs.append(f"{k}={_quote(v)}")
    if not pairs:
        return ""
    return " [" + ", ".join(pairs) + "]"


def _collect_local_nodes(graph: "Graph") -> list["Node"]:
    """Return nodes that belong directly to this graph, not its subgraphs."""
    subgraph_nodes = set()
    for sub in graph.subgraphs.values():
        subgraph_nodes.update(sub.nodes.keys())
    return [n for name, n in graph.nodes.items() if name not in subgraph_nodes]


def _collect_local_edges(graph: "Graph") -> list["Edge"]:
    """Return edges that belong directly to this graph, not its subgraphs."""
    subgraph_edge_keys = set()
    for sub in graph.subgraphs.values():
        subgraph_edge_keys.update(sub.edges.keys())
    return [e for key, e in graph.edges.items() if key not in subgraph_edge_keys]


def _write_subgraph(graph: "Graph", indent: str, edge_op: str) -> list[str]:
    """Recursively write a subgraph block."""
    lines = []
    name = _quote(graph.name) if graph.name else ""
    lines.append(f"{indent}subgraph {name} {{")
    inner = indent + "    "

    # Subgraph-local attributes (from attr_record, not the shared attr_dict_g)
    if hasattr(graph, "attr_record"):
        for k, v in graph.attr_record.items():
            if v is not None and v != "" and not k.startswith("_"):
                lines.append(f"{inner}{k}={_quote(v)};")

    # Nested subgraphs
    for sub in graph.subgraphs.values():
        lines.extend(_write_subgraph(sub, inner, edge_op))

    # Local nodes
    for node in _collect_local_nodes(graph):
        attrs = {k: v for k, v in node.attributes.items()
                 if v is not None and v != "" and not k.startswith("_")}
        lines.append(f"{inner}{_quote(node.name)}{_format_attrs(attrs)};")

    # Local edges
    for edge in _collect_local_edges(graph):
        tail = _quote(edge.tail.name)
        head = _quote(edge.head.name)
        attrs = {k: v for k, v in edge.attributes.items()
                 if v is not None and v != "" and not k.startswith("_")}
        lines.append(f"{inner}{tail} {edge_op} {head}{_format_attrs(attrs)};")

    lines.append(f"{indent}}}")
    return lines


def write_gv(graph: "Graph") -> str:
    """Serialize a Graph object to GV/DOT-language text.

    Returns a string containing valid DOT that can be parsed by
    Graphviz or ``read_gv()``.
    """
    # Graph type
    strict = "strict " if graph.strict else ""
    gtype = "digraph" if graph.directed else "graph"
    edge_op = "->" if graph.directed else "--"
    name = _quote(graph.name) if graph.name else ""

    lines = [f"{strict}{gtype} {name} {{"]
    indent = "    "

    # Graph-level attributes
    if hasattr(graph, "attr_dict_g"):
        for k, v in graph.attr_dict_g.items():
            if v is not None and v != "":
                lines.append(f"{indent}{k}={_quote(v)};")

    # Default node attributes
    if hasattr(graph, "attr_dict_n") and graph.attr_dict_n:
        node_defaults = {k: v for k, v in graph.attr_dict_n.items()
                         if v is not None and v != ""}
        if node_defaults:
            lines.append(f"{indent}node{_format_attrs(node_defaults)};")

    # Default edge attributes
    if hasattr(graph, "attr_dict_e") and graph.attr_dict_e:
        edge_defaults = {k: v for k, v in graph.attr_dict_e.items()
                         if v is not None and v != ""}
        if edge_defaults:
            lines.append(f"{indent}edge{_format_attrs(edge_defaults)};")

    # Subgraphs
    for sub in graph.subgraphs.values():
        lines.extend(_write_subgraph(sub, indent, edge_op))

    # Local nodes (not in any subgraph)
    for node in _collect_local_nodes(graph):
        attrs = {k: v for k, v in node.attributes.items()
                 if v is not None and v != "" and not k.startswith("_")}
        lines.append(f"{indent}{_quote(node.name)}{_format_attrs(attrs)};")

    # Local edges (not in any subgraph)
    for edge in _collect_local_edges(graph):
        tail = _quote(edge.tail.name)
        head = _quote(edge.head.name)
        attrs = {k: v for k, v in edge.attributes.items()
                 if v is not None and v != "" and not k.startswith("_")}
        lines.append(f"{indent}{tail} {edge_op} {head}{_format_attrs(attrs)};")

    lines.append("}")
    return "\n".join(lines) + "\n"


def write_gv_file(graph: "Graph", filepath: str) -> None:
    """Write a Graph object to a GV/DOT file."""
    from pathlib import Path
    Path(filepath).write_text(write_gv(graph), encoding="utf-8")


# Backward-compatible aliases
write_dot = write_gv
write_dot_file = write_gv_file
