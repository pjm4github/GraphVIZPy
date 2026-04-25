"""
GVGraphVisitor — walks the ANTLR4 parse tree and constructs
gvpy.core.graph.Graph objects.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure generated grammar modules are importable
_generated_dir = str(Path(__file__).resolve().parent / "generated")
if _generated_dir not in sys.path:
    sys.path.insert(0, _generated_dir)

from GVParser import GVParser                          # noqa: E402
from GVParserVisitor import GVParserVisitor             # noqa: E402

from gvpy.core.graph import Graph                    # noqa: E402
from gvpy.core.node import Node                      # noqa: E402
from gvpy.core.headers import Agdesc                   # noqa: E402


class GVGraphVisitor(GVParserVisitor):
    """Visits a GV/DOT parse tree and produces a Graph object."""

    def __init__(self):
        self.graph: Graph | None = None
        self._graph_stack: list[Graph] = []
        self._default_node_attrs: dict[str, str] = {}
        self._default_edge_attrs: dict[str, str] = {}
        self._directed: bool = False
        self._anon_counter: int = 0

    @property
    def _current(self) -> Graph:
        return self._graph_stack[-1]

    # ── graph rule ────────────────────────────────
    def visitGraph(self, ctx: GVParser.GraphContext):
        strict = ctx.KW_STRICT() is not None
        self._directed = ctx.graphType().KW_DIGRAPH() is not None
        name = self._get_id_text(ctx.id_()) if ctx.id_() else ""

        self.graph = Graph(
            name=name,
            directed=self._directed,
            strict=strict,
        )
        self.graph.method_init()
        self._graph_stack.append(self.graph)
        self.visitStmtList(ctx.stmtList())
        self._graph_stack.pop()
        return self.graph

    # ── stmtList rule ─────────────────────────────
    def visitStmtList(self, ctx: GVParser.StmtListContext):
        for stmt_ctx in ctx.stmt():
            self.visitStmt(stmt_ctx)

    # ── stmt rule ─────────────────────────────────
    def visitStmt(self, ctx: GVParser.StmtContext):
        if ctx.attrStmt():
            self.visitAttrStmt(ctx.attrStmt())
        elif ctx.edgeStmt():
            self.visitEdgeStmt(ctx.edgeStmt())
        elif ctx.subgraph():
            self.visitSubgraph(ctx.subgraph())
        elif ctx.nodeStmt():
            self.visitNodeStmt(ctx.nodeStmt())
        elif ctx.EQUALS():
            # graph-level attribute: id = id
            ids = ctx.id_()
            key = self._get_id_text(ids[0])
            value = self._get_id_text(ids[1])
            self._current.set_graph_attr(key, value)

    # ── attrStmt rule ─────────────────────────────
    def visitAttrStmt(self, ctx: GVParser.AttrStmtContext):
        attrs = self._get_attrs(ctx.attrList())
        if ctx.KW_GRAPH():
            for k, v in attrs.items():
                self._current.set_graph_attr(k, v)
        elif ctx.KW_NODE():
            self._default_node_attrs.update(attrs)
        elif ctx.KW_EDGE():
            self._default_edge_attrs.update(attrs)

    # ── nodeStmt rule ─────────────────────────────
    def visitNodeStmt(self, ctx: GVParser.NodeStmtContext):
        name = self._get_id_text(ctx.nodeId().id_())
        node = self._current.add_node(name, create=True)
        if node is None:
            return
        # Apply default attrs first, then inline attrs override
        for k, v in self._default_node_attrs.items():
            node.agset(k, v)
        if ctx.nodeId().port():
            node.agset("port", self._get_port_text(ctx.nodeId().port()))
        if ctx.attrList():
            for k, v in self._get_attrs(ctx.attrList()).items():
                node.agset(k, v)

    # ── edgeStmt rule ─────────────────────────────
    def visitEdgeStmt(self, ctx: GVParser.EdgeStmtContext):
        # Collect chain of endpoints as (name_or_graph, port_string)
        endpoints = []
        if ctx.nodeId():
            name, port = self._resolve_node_id(ctx.nodeId())
            endpoints.append((name, port))
        elif ctx.subgraph():
            endpoints.append((self.visitSubgraph(ctx.subgraph()), ""))

        for rhs in ctx.edgeRhs():
            if rhs.nodeId():
                name, port = self._resolve_node_id(rhs.nodeId())
                endpoints.append((name, port))
            elif rhs.subgraph():
                endpoints.append((self.visitSubgraph(rhs.subgraph()), ""))

        # Collect inline attrs
        inline_attrs = self._get_attrs(ctx.attrList()) if ctx.attrList() else {}
        merged_attrs = {**self._default_edge_attrs, **inline_attrs}

        # Create edges pairwise through the chain
        for i in range(len(endpoints) - 1):
            tail_ep, tail_port = endpoints[i]
            head_ep, head_port = endpoints[i + 1]
            tail_nodes = self._expand_endpoint(tail_ep)
            head_nodes = self._expand_endpoint(head_ep)
            for tail_name in tail_nodes:
                for head_name in head_nodes:
                    edge = self._current.add_edge(tail_name, head_name)
                    if edge is not None:
                        for k, v in merged_attrs.items():
                            edge.agset(k, v)
                        # Store ports from node_id syntax (a:port -> b:port)
                        if tail_port and not edge.attributes.get("tailport"):
                            edge.agset("tailport", tail_port)
                        if head_port and not edge.attributes.get("headport"):
                            edge.agset("headport", head_port)

    # ── subgraph rule ─────────────────────────────
    def visitSubgraph(self, ctx: GVParser.SubgraphContext):
        name = ""
        if ctx.KW_SUBGRAPH():
            if ctx.id_():
                name = self._get_id_text(ctx.id_())
        if not name:
            name = f"_anonymous_{self._anon_counter}"
            self._anon_counter += 1

        subg = self._current.add_subgraph(name, create=True)
        if subg is None:
            subg = self._current.subgraphs.get(name)
        self._graph_stack.append(subg)
        self.visitStmtList(ctx.stmtList())
        self._graph_stack.pop()
        return subg

    # ── helpers ───────────────────────────────────

    def _resolve_node_id(self, ctx: GVParser.NodeIdContext) -> tuple[str, str]:
        """Resolve a node_id context used as an *edge endpoint*:
        ensure the node exists (creating it in the root graph if
        needed) but do NOT register it as a member of the current
        subgraph.  A node becomes a cluster member only via a
        ``node_stmt`` declaration inside the subgraph body — not via
        an edge that references it.  See
        ``Docs/declared_vs_referenced_proposal.md``.
        """
        name = self._get_id_text(ctx.id_())
        self._current.add_node(name, create=True, declared=False)
        port = self._get_port_text(ctx.port()) if ctx.port() else ""
        return name, port

    def _expand_endpoint(self, endpoint) -> list[str]:
        """Expand an endpoint to a list of node names.
        If endpoint is a string, it's a single node name.
        If endpoint is a Graph (subgraph), return all node names in it.
        """
        if isinstance(endpoint, str):
            return [endpoint]
        elif isinstance(endpoint, Graph):
            return list(endpoint.nodes.keys()) if endpoint.nodes else []
        return []

    def _get_id_text(self, ctx: GVParser.Id_Context) -> str:
        """Extract the string value from an id_ context."""
        if ctx is None:
            return ""
        if ctx.QUOTED_STRING():
            return self._unescape(ctx.QUOTED_STRING().getText())
        if ctx.htmlString():
            return self._get_html_text(ctx.htmlString())
        # ID or NUMBER
        return ctx.getText()

    def _get_html_text(self, ctx: GVParser.HtmlStringContext) -> str:
        """Reconstruct HTML string content including angle brackets."""
        parts = []
        for child in ctx.htmlContent():
            parts.append(self._get_html_content_text(child))
        return "<" + "".join(parts) + ">"

    def _get_html_content_text(self, ctx: GVParser.HtmlContentContext) -> str:
        """Recursively reconstruct HTML content."""
        if ctx.HTML_TEXT():
            return ctx.HTML_TEXT().getText()
        # Nested <...>
        parts = []
        for child in ctx.htmlContent():
            parts.append(self._get_html_content_text(child))
        return "<" + "".join(parts) + ">"

    def _get_attrs(self, ctx: GVParser.AttrListContext) -> dict[str, str]:
        """Extract all key=value pairs from an attrList context."""
        attrs = {}
        if ctx is None:
            return attrs
        for a_list_ctx in ctx.aList():
            ids = a_list_ctx.id_()
            # ids come in pairs: key, value, key, value, ...
            for i in range(0, len(ids) - 1, 2):
                key = self._get_id_text(ids[i])
                value = self._get_id_text(ids[i + 1])
                attrs[key] = value
        return attrs

    def _get_port_text(self, ctx: GVParser.PortContext) -> str:
        """Extract port specification as a string."""
        ids = ctx.id_()
        if len(ids) == 2:
            return self._get_id_text(ids[0]) + ":" + self._get_id_text(ids[1])
        return self._get_id_text(ids[0])

    @staticmethod
    def _unescape(s: str) -> str:
        """Process escape sequences in a DOT quoted string."""
        # Strip outer quotes
        s = s[1:-1]
        result = []
        i = 0
        while i < len(s):
            if s[i] == '\\' and i + 1 < len(s):
                c = s[i + 1]
                if c == '"':
                    result.append('"')
                elif c == '\\':
                    result.append('\\')
                elif c == 'n':
                    result.append('\n')
                elif c == 't':
                    result.append('\t')
                elif c == 'r':
                    result.append('\r')
                elif c == 'l':
                    result.append('\n')  # left-justified line break
                else:
                    # Preserve unrecognized escapes (e.g. \G, \N, \E)
                    result.append('\\')
                    result.append(c)
                i += 2
            else:
                result.append(s[i])
                i += 1
        return ''.join(result)
