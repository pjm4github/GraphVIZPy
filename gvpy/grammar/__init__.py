"""
GV grammar package — ANTLR4 lexer, parser, reader, and writer for the
Graphviz DOT language.

Contains the grammar definitions (GVLexer.g4, GVParser.g4), the
auto-generated parser code, and the Python API for reading and writing
GV/DOT text.

To regenerate after editing .g4 files::

    gvpy\\grammar\\build_grammar.bat
"""
from .gv_reader import (
    read_gv, read_gv_file, read_gv_all, read_gv_file_all,
    GVParseError,
    # Backward-compatible aliases
    read_dot, read_dot_file, read_dot_all, read_dot_file_all,
    DOTParseError,
)
from .gv_writer import (
    write_gv, write_gv_file,
    # Backward-compatible aliases
    write_dot, write_dot_file,
)
