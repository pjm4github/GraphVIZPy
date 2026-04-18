"""
Public API for parsing GV (DOT) language text into Graph objects.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Union

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

# Ensure generated grammar modules are importable
_generated_dir = str(Path(__file__).resolve().parent / "generated")
if _generated_dir not in sys.path:
    sys.path.insert(0, _generated_dir)

from GVLexer import GVLexer            # noqa: E402
from GVParser import GVParser          # noqa: E402

from gvpy.grammar.gv_visitor import GVGraphVisitor  # noqa: E402
from gvpy.grammar.record_parser import parse_record_label  # noqa: E402
from gvpy.core.graph import Graph                  # noqa: E402


class GVParseError(Exception):
    """Raised when GV/DOT parsing fails."""
    pass


# Backward-compatible alias
DOTParseError = GVParseError


class _SilentErrorListener(ErrorListener):
    """Collects parse errors instead of printing to stderr."""

    def __init__(self):
        super().__init__()
        self.errors: list[str] = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append(f"line {line}:{column} {msg}")


def _init_record_fields(graph: Graph):
    """Parse record labels into field trees on Node objects.

    For each node with shape=record or shape=Mrecord, parses the label
    attribute into a RecordField tree and stores it on node.record_fields.

    C reference: shapes.c:3687 record_init() called from
    dotinit.c:45 dot_init_node().
    """
    # Default node shape may come from graph-level "node" defaults
    # (e.g., node [shape=Mrecord]).  Check the graph's node attr dict.
    default_shape = getattr(graph, 'attr_dict_n', {}).get("shape", "")
    for node in graph.nodes.values():
        shape = node.attributes.get("shape", default_shape).lower()
        if shape in ("record", "mrecord"):
            label = node.attributes.get("label", node.name)
            try:
                node.record_fields = parse_record_label(label)
            except Exception:
                pass  # malformed label — leave record_fields as None

    # Recurse into subgraphs (nodes may be defined in subgraphs)
    def _walk_subgraphs(g):
        for sub in g.subgraphs.values():
            for node in sub.nodes.values():
                if node.record_fields is not None:
                    continue  # already parsed
                shape = node.attributes.get("shape", "").lower()
                if shape in ("record", "mrecord"):
                    label = node.attributes.get("label", node.name)
                    try:
                        node.record_fields = parse_record_label(label)
                    except Exception:
                        pass
            _walk_subgraphs(sub)
    _walk_subgraphs(graph)


def _sanitize_dot(text: str) -> str:
    """Replace non-ASCII characters that the ANTLR lexer cannot tokenise.

    C Graphviz treats identifiers as raw byte strings and never rejects
    non-ASCII input.  The ANTLR4-generated lexer only recognises the
    printable ASCII range, so corrupted / ISO-8859 / fuzz-test files
    produce 'token recognition error' on every non-ASCII byte.

    Fix: replace any character outside the printable-ASCII + common
    whitespace range with underscore.  This preserves the DOT structure
    while making corrupted identifiers parseable.
    """
    out = []
    for ch in text:
        cp = ord(ch)
        if cp == 0x09 or cp == 0x0A or cp == 0x0D:  # tab, LF, CR
            out.append(ch)
        elif 0x20 <= cp <= 0x7E:  # printable ASCII
            out.append(ch)
        else:
            out.append('_')
    return "".join(out)


def read_gv(text: str) -> Graph:
    """Parse a GV/DOT-language string and return a Graph object.

    If the input contains multiple graph blocks (e.g. two ``digraph``
    declarations), only the first block is parsed.

    Non-ASCII bytes are replaced with underscores so that corrupted or
    ISO-8859-encoded files can still be parsed.

    Raises GVParseError if the input contains syntax errors.
    """
    text = _sanitize_dot(text)

    # Handle multiple graph blocks — parse only the first one.
    blocks = _split_graph_blocks(text)
    if len(blocks) > 1:
        text = blocks[0]

    input_stream = InputStream(text)

    lexer = GVLexer(input_stream)
    error_listener = _SilentErrorListener()
    lexer.removeErrorListeners()
    lexer.addErrorListener(error_listener)

    token_stream = CommonTokenStream(lexer)

    parser = GVParser(token_stream)
    parser.removeErrorListeners()
    parser.addErrorListener(error_listener)

    tree = parser.graph()

    if error_listener.errors:
        # Best-effort: if the tree has children (partial parse succeeded),
        # log warnings but continue.  Only raise if the tree is empty
        # (complete parse failure).
        if tree is None or tree.getChildCount() == 0:
            raise GVParseError(
                "Parse errors:\n" + "\n".join(error_listener.errors)
            )

    visitor = GVGraphVisitor()
    graph = visitor.visit(tree)

    # Post-parse: parse record labels into field trees on Node objects.
    # C does this in record_init() during dot_init_node() (shapes.c:3687,
    # dotinit.c:45).  We do it here so the field tree is available to
    # all consumers (layout engines, renderers, pictosync).
    _init_record_fields(graph)

    return graph


# Backward-compatible alias
read_dot = read_gv


def read_gv_all(text: str) -> list[Graph]:
    """Parse a GV/DOT string that may contain multiple graph blocks.

    Returns a list of Graph objects, one per top-level graph block.
    """
    blocks = _split_graph_blocks(text)
    if not blocks:
        raise GVParseError("No graph blocks found")
    return [read_gv(block) for block in blocks]


# Backward-compatible alias
read_dot_all = read_gv_all


def _split_graph_blocks(text: str) -> list[str]:
    """Split text into individual graph blocks by tracking brace nesting."""
    pattern = re.compile(
        r'(?:^|\n)\s*(?:strict\s+)?(?:di)?graph\b',
        re.IGNORECASE,
    )
    starts = [m.start() for m in pattern.finditer(text)]
    if len(starts) <= 1:
        return [text.strip()] if text.strip() else []

    blocks = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        block = text[start:end].strip()
        if block:
            blocks.append(block)
    return blocks


def read_gv_file(filepath: Union[str, Path]) -> Graph:
    """Read a GV/DOT file from disk and parse it into a Graph object.

    Tries UTF-8 first, falls back to latin-1 for legacy files.
    """
    path = Path(filepath)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    return read_gv(text)


# Backward-compatible alias
read_dot_file = read_gv_file


def read_gv_file_all(filepath: Union[str, Path]) -> list[Graph]:
    """Read a GV/DOT file containing multiple graphs.

    Tries UTF-8 first, falls back to latin-1.
    """
    path = Path(filepath)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    return read_gv_all(text)


# Backward-compatible alias
read_dot_file_all = read_gv_file_all
