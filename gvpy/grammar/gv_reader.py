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


def read_gv(text: str) -> Graph:
    """Parse a GV/DOT-language string and return a Graph object.

    Raises GVParseError if the input contains syntax errors.
    """
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
        raise GVParseError(
            "Parse errors:\n" + "\n".join(error_listener.errors)
        )

    visitor = GVGraphVisitor()
    graph = visitor.visit(tree)
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
