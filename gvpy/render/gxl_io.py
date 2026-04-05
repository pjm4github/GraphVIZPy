"""
GXL (Graph eXchange Language) reader/writer — XML-based graph interchange.

GXL is an XML format for typed, attributed graphs.  This module supports:

- Directed and undirected graphs (``edgemode`` attribute)
- Node and edge attributes with typed values (``<string>``, ``<int>``,
  ``<float>``, ``<bool>``, ``<enum>``)
- Subgraphs as nested ``<graph>`` elements
- Multiple graphs per file
- Node/edge IDs mapped to core names

File extension: ``.gxl``

GXL Structure::

    <?xml version="1.0" encoding="UTF-8"?>
    <gxl xmlns:xlink="http://www.w3.org/1999/xlink">
      <graph id="G" edgemode="directed">
        <node id="A">
          <attr name="label"><string>Node A</string></attr>
        </node>
        <edge from="A" to="B">
          <attr name="color"><string>red</string></attr>
        </edge>
      </graph>
    </gxl>

Reference: http://www.gupro.de/GXL/
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Union
from xml.etree import ElementTree as ET
from xml.dom import minidom

if TYPE_CHECKING:
    from gvpy.core.graph import Graph


# ── Writer ──────────────────────────────────────────────────────


def _typed_value_element(value: str) -> ET.Element:
    """Create a typed GXL value element from a string attribute value.

    Attempts to infer the type: bool, int, float, or string.
    """
    low = value.lower()
    if low in ("true", "false"):
        el = ET.Element("bool")
        el.text = low
        return el
    try:
        int(value)
        el = ET.Element("int")
        el.text = value
        return el
    except ValueError:
        pass
    try:
        float(value)
        el = ET.Element("float")
        el.text = value
        return el
    except ValueError:
        pass
    el = ET.Element("string")
    el.text = value
    return el


def _add_attrs(parent: ET.Element, attrs: dict[str, str]):
    """Add <attr> elements to a GXL parent element."""
    for k, v in attrs.items():
        if v is None or v == "" or k.startswith("_"):
            continue
        attr_el = ET.SubElement(parent, "attr", name=k)
        attr_el.append(_typed_value_element(v))


def _write_subgraph(parent: ET.Element, graph: "Graph",
                    edgemode: str, written_nodes: set):
    """Recursively write a subgraph as a nested <graph> element."""
    graph_el = ET.SubElement(parent, "graph",
                             id=graph.name or "",
                             edgemode=edgemode)

    # Subgraph-level attributes (from attr_record for local attrs)
    if hasattr(graph, "attr_record"):
        sub_attrs = {k: v for k, v in graph.attr_record.items()
                     if v is not None and v != "" and not k.startswith("_")}
        _add_attrs(graph_el, sub_attrs)

    # Nested subgraphs first
    for sub in graph.subgraphs.values():
        _write_subgraph(graph_el, sub, edgemode, written_nodes)

    # Nodes in this subgraph
    for name, node in graph.nodes.items():
        if name in written_nodes:
            continue
        written_nodes.add(name)
        node_el = ET.SubElement(graph_el, "node", id=name)
        node_attrs = {k: v for k, v in node.attributes.items()
                      if v is not None and v != "" and not k.startswith("_")}
        _add_attrs(node_el, node_attrs)

    # Edges in this subgraph
    for key, edge in graph.edges.items():
        tail_name = edge.tail.name
        head_name = edge.head.name
        edge_el = ET.SubElement(graph_el, "edge")
        edge_el.set("from", tail_name)
        edge_el.set("to", head_name)
        edge_attrs = {k: v for k, v in edge.attributes.items()
                      if v is not None and v != "" and not k.startswith("_")}
        _add_attrs(edge_el, edge_attrs)


def write_gxl(graph: "Graph") -> str:
    """Serialize a Graph object to GXL (Graph eXchange Language) XML.

    Parameters
    ----------
    graph : Graph
        The graph to serialize.

    Returns
    -------
    str
        GXL XML text.
    """
    gxl = ET.Element("gxl")
    gxl.set("xmlns:xlink", "http://www.w3.org/1999/xlink")

    edgemode = "directed" if graph.directed else "undirected"
    graph_el = ET.SubElement(gxl, "graph",
                              id=graph.name or "G",
                              edgemode=edgemode)

    # Graph-level attributes
    if hasattr(graph, "attr_dict_g"):
        graph_attrs = {k: v for k, v in graph.attr_dict_g.items()
                       if v is not None and v != ""}
        _add_attrs(graph_el, graph_attrs)

    # Track which nodes have been written (to avoid duplicates in subgraphs)
    written_nodes: set[str] = set()

    # Subgraphs as nested <graph> elements
    for sub in graph.subgraphs.values():
        _write_subgraph(graph_el, sub, edgemode, written_nodes)

    # Top-level nodes (not in any subgraph)
    for name, node in graph.nodes.items():
        if name in written_nodes:
            continue
        written_nodes.add(name)
        node_el = ET.SubElement(graph_el, "node", id=name)
        node_attrs = {k: v for k, v in node.attributes.items()
                      if v is not None and v != "" and not k.startswith("_")}
        _add_attrs(node_el, node_attrs)

    # Top-level edges
    subgraph_edge_keys = set()
    for sub in graph.subgraphs.values():
        subgraph_edge_keys.update(sub.edges.keys())

    for key, edge in graph.edges.items():
        if key in subgraph_edge_keys:
            continue
        tail_name = edge.tail.name
        head_name = edge.head.name
        edge_el = ET.SubElement(graph_el, "edge")
        edge_el.set("from", tail_name)
        edge_el.set("to", head_name)
        edge_attrs = {k: v for k, v in edge.attributes.items()
                      if v is not None and v != "" and not k.startswith("_")}
        _add_attrs(edge_el, edge_attrs)

    # Pretty-print
    rough = ET.tostring(gxl, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(rough)
    pretty = dom.toprettyxml(indent="  ", encoding=None)
    # Remove extra XML declaration from minidom (we'll add our own)
    lines = pretty.split("\n")
    if lines and lines[0].startswith("<?xml"):
        lines = lines[1:]
    xml_decl = '<?xml version="1.0" encoding="UTF-8"?>'
    return xml_decl + "\n" + "\n".join(lines)


def write_gxl_file(graph: "Graph", filepath: str) -> None:
    """Write a Graph object to a GXL file."""
    Path(filepath).write_text(write_gxl(graph), encoding="utf-8")


# ── Reader ──────────────────────────────────────────────────────


def _parse_typed_value(el: ET.Element) -> str:
    """Extract a string value from a typed GXL value element."""
    tag = el.tag
    text = (el.text or "").strip()
    if tag == "bool":
        return text.lower()
    return text


def _read_attrs(element: ET.Element) -> dict[str, str]:
    """Read <attr> children from a GXL element into a dict."""
    attrs = {}
    for attr_el in element.findall("attr"):
        name = attr_el.get("name", "")
        if not name:
            continue
        # The value is in the first child element
        for child in attr_el:
            attrs[name] = _parse_typed_value(child)
            break
    return attrs


def _read_subgraph(graph_el: ET.Element, parent_graph: "Graph"):
    """Recursively read a nested <graph> element as a subgraph."""
    sub_name = graph_el.get("id", "")
    if not sub_name:
        sub_name = f"subgraph_{id(graph_el)}"

    sub = parent_graph.create_subgraph(sub_name)

    # Subgraph attributes (stored in attr_record for subgraph-local attrs)
    attrs = _read_attrs(graph_el)
    for k, v in attrs.items():
        sub.attr_record[k] = v

    # Nested subgraphs
    for nested in graph_el.findall("graph"):
        _read_subgraph(nested, sub)

    # Nodes
    for node_el in graph_el.findall("node"):
        node_name = node_el.get("id", "")
        if not node_name:
            continue
        # Add to root graph first (if not already), then to subgraph
        root = parent_graph
        while hasattr(root, "parent_graph") and root.parent_graph:
            root = root.parent_graph
        if node_name not in root.nodes:
            node = root.add_node(node_name)
        else:
            node = root.nodes[node_name]
        sub.add_node(node_name)

        node_attrs = _read_attrs(node_el)
        for k, v in node_attrs.items():
            node.agset(k, v)

    # Edges
    for edge_el in graph_el.findall("edge"):
        tail = edge_el.get("from", "")
        head = edge_el.get("to", "")
        if not tail or not head:
            continue
        root = parent_graph
        while hasattr(root, "parent_graph") and root.parent_graph:
            root = root.parent_graph
        edge = root.add_edge(tail, head)
        edge_attrs = _read_attrs(edge_el)
        for k, v in edge_attrs.items():
            edge.agset(k, v)


def read_gxl(text: str) -> "Graph":
    """Parse GXL XML text into a Graph object.

    If the GXL contains multiple ``<graph>`` elements at the top level,
    only the first is returned.  Use ``read_gxl_all()`` for multiple graphs.

    Parameters
    ----------
    text : str
        GXL XML text.

    Returns
    -------
    Graph
        A fully constructed Graph object.
    """
    from gvpy.core.graph import Graph

    root = ET.fromstring(text)

    # Find the first <graph> element (may be direct child of <gxl> or root itself)
    if root.tag == "gxl":
        graph_el = root.find("graph")
    elif root.tag == "graph":
        graph_el = root
    else:
        raise ValueError(f"Expected <gxl> or <graph> root element, got <{root.tag}>")

    if graph_el is None:
        raise ValueError("No <graph> element found in GXL input")

    name = graph_el.get("id", "G")
    edgemode = graph_el.get("edgemode", "directed")
    directed = edgemode != "undirected"

    g = Graph(name, directed=directed)
    g.method_init()

    # Graph-level attributes
    attrs = _read_attrs(graph_el)
    for k, v in attrs.items():
        g.set_graph_attr(k, v)

    # Nested subgraphs
    for nested in graph_el.findall("graph"):
        _read_subgraph(nested, g)

    # Top-level nodes
    for node_el in graph_el.findall("node"):
        node_name = node_el.get("id", "")
        if not node_name:
            continue
        if node_name not in g.nodes:
            node = g.add_node(node_name)
        else:
            node = g.nodes[node_name]
        node_attrs = _read_attrs(node_el)
        for k, v in node_attrs.items():
            node.agset(k, v)

    # Top-level edges
    for edge_el in graph_el.findall("edge"):
        tail = edge_el.get("from", "")
        head = edge_el.get("to", "")
        if not tail or not head:
            continue
        edge = g.add_edge(tail, head)
        edge_attrs = _read_attrs(edge_el)
        for k, v in edge_attrs.items():
            edge.agset(k, v)

    return g


def read_gxl_all(text: str) -> list["Graph"]:
    """Parse GXL XML text containing multiple <graph> elements.

    Returns a list of Graph objects.
    """
    from gvpy.core.graph import Graph

    root = ET.fromstring(text)
    graphs = []

    graph_els = root.findall("graph") if root.tag == "gxl" else [root]
    for graph_el in graph_els:
        name = graph_el.get("id", "G")
        edgemode = graph_el.get("edgemode", "directed")
        directed = edgemode != "undirected"

        g = Graph(name, directed=directed)
        g.method_init()

        attrs = _read_attrs(graph_el)
        for k, v in attrs.items():
            g.set_graph_attr(k, v)

        for nested in graph_el.findall("graph"):
            _read_subgraph(nested, g)

        for node_el in graph_el.findall("node"):
            node_name = node_el.get("id", "")
            if not node_name:
                continue
            if node_name not in g.nodes:
                node = g.add_node(node_name)
            else:
                node = g.nodes[node_name]
            node_attrs = _read_attrs(node_el)
            for k, v in node_attrs.items():
                node.agset(k, v)

        for edge_el in graph_el.findall("edge"):
            tail = edge_el.get("from", "")
            head = edge_el.get("to", "")
            if not tail or not head:
                continue
            edge = g.add_edge(tail, head)
            edge_attrs = _read_attrs(edge_el)
            for k, v in edge_attrs.items():
                edge.agset(k, v)

        graphs.append(g)

    return graphs


def read_gxl_file(filepath: Union[str, Path]) -> "Graph":
    """Read a GXL file and parse it into a Graph object."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8")
    return read_gxl(text)
