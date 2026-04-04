"""
Public API for parsing DOT language text into Graph objects.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Union

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

# Ensure generated modules are importable
_generated_dir = str(Path(__file__).resolve().parent / "generated")
if _generated_dir not in sys.path:
    sys.path.insert(0, _generated_dir)

from DOTLexer import DOTLexer          # noqa: E402
from DOTParser import DOTParser        # noqa: E402

from pycode.dot.dot_visitor import DOTGraphVisitor  # noqa: E402
from pycode.cgraph.graph import Graph                    # noqa: E402


class DOTParseError(Exception):
    """Raised when DOT parsing fails."""
    pass


class _SilentErrorListener(ErrorListener):
    """Collects parse errors instead of printing to stderr."""

    def __init__(self):
        super().__init__()
        self.errors: list[str] = []

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        self.errors.append(f"line {line}:{column} {msg}")


def read_dot(text: str) -> Graph:
    """Parse a DOT-language string and return a Graph object.

    Raises DOTParseError if the input contains syntax errors.
    """
    input_stream = InputStream(text)

    lexer = DOTLexer(input_stream)
    error_listener = _SilentErrorListener()
    lexer.removeErrorListeners()
    lexer.addErrorListener(error_listener)

    token_stream = CommonTokenStream(lexer)

    parser = DOTParser(token_stream)
    parser.removeErrorListeners()
    parser.addErrorListener(error_listener)

    tree = parser.graph()

    if error_listener.errors:
        raise DOTParseError(
            "Parse errors:\n" + "\n".join(error_listener.errors)
        )

    visitor = DOTGraphVisitor()
    graph = visitor.visit(tree)
    return graph


def read_dot_all(text: str) -> list[Graph]:
    """Parse a DOT string that may contain multiple graph blocks.

    Returns a list of Graph objects, one per top-level graph block.
    """
    # Split on top-level graph boundaries by tracking brace depth
    blocks = _split_graph_blocks(text)
    if not blocks:
        raise DOTParseError("No graph blocks found")
    return [read_dot(block) for block in blocks]


def _split_graph_blocks(text: str) -> list[str]:
    """Split text into individual graph blocks by tracking brace nesting."""
    # Find starts of graph blocks: (strict)? (di)?graph
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


def read_dot_file(filepath: Union[str, Path]) -> Graph:
    """Read a DOT file from disk and parse it into a Graph object.

    Tries UTF-8 first, falls back to latin-1 for legacy files.
    """
    path = Path(filepath)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    return read_dot(text)


def read_dot_file_all(filepath: Union[str, Path]) -> list[Graph]:
    """Read a DOT file containing multiple graphs.

    Tries UTF-8 first, falls back to latin-1.
    """
    path = Path(filepath)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="latin-1")
    return read_dot_all(text)
