"""Context-aware DOT syntax highlighter for Qt text editors.

A :class:`DotSyntaxHighlighter` (subclass of
:class:`QSyntaxHighlighter`) drives the colorization of a
``QTextDocument`` containing Graphviz DOT source.  Rather than
hardcoding the keyword list, the highlighter **extracts the
lexer rules from** ``gvpy/grammar/GVLexer.g4`` at module-load
time so anyone modifying the grammar (renaming a keyword,
adding a new edge operator, etc.) automatically gets the
matching highlighting without touching this file.

The grammar parser is conservative — it only looks for the
patterns it explicitly recognises (``KW_FOO : F O O ;``,
``DIRECTED_EDGE : '->';``, etc.).  Anything it can't parse
falls through to a hardcoded baseline so the highlighter never
ends up blank.

Highlighted token classes:

- **Keywords** (``graph``, ``digraph``, ``strict``, ``node``,
  ``edge``, ``subgraph``) — case-insensitive, derived from
  ``KW_*`` rules in the grammar.  Bold blue.
- **Edge operators** (``->``, ``--``) — derived from
  ``*_EDGE`` rules.  Bold purple.
- **Punctuation** (``{ } [ ] ; , : =``) — dark gray.
- **String literals** (``"..."`` with backslash escapes) —
  dark green.
- **HTML labels** (``<...>``) — orange / dark yellow.  Single
  line only; multi-line nested HTML labels (rare) get
  partially-colored spans.
- **Numbers** (integers, decimals, signed) — teal.
- **Comments** — gray italic.  ``//`` line comments,
  ``/* */`` block comments, and ``#`` preprocessor lines all
  styled the same.
- **Identifiers** — default editor color.

The Qt imports happen inside a guard so this module can be
imported in non-GUI contexts (e.g., for inspecting the
extracted rules) without requiring PyQt6 to be installed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# Grammar parsing
# ─────────────────────────────────────────────────────────────────


@dataclass
class GrammarRules:
    """Rules extracted from ``GVLexer.g4``.

    Public attributes are populated by :func:`_parse_grammar`:

    - ``keywords`` — list of lowercased keyword strings
      (``["strict", "graph", "digraph", "node", "edge",
      "subgraph"]``).
    - ``edge_operators`` — list of edge-operator literals
      (``["->", "--"]``).  Order is preserved from the grammar.
    - ``punctuation`` — list of single-char punctuation
      literals (``["{", "}", "[", "]", ";", ",", ":", "="]``).
    """
    keywords: list[str]
    edge_operators: list[str]
    punctuation: list[str]


# These mirror what ``GVLexer.g4`` defines today; used as the
# fallback when grammar parsing fails (e.g. .g4 file removed
# from an installed wheel) or returns an empty list.
_FALLBACK_KEYWORDS: list[str] = [
    "strict", "graph", "digraph", "node", "edge", "subgraph",
]
_FALLBACK_EDGE_OPERATORS: list[str] = ["->", "--"]
_FALLBACK_PUNCTUATION: list[str] = [
    "{", "}", "[", "]", ";", ",", ":", "=",
]


# Regex matching ``KW_NAME : F R A G ;`` style keyword rules.
# Captures the right-hand side as a sequence of single-letter
# fragment references.
_KW_RULE_RE = re.compile(
    r"^\s*KW_\w+\s*:\s*([A-Z](?:\s+[A-Z])*)\s*;",
    re.MULTILINE,
)

# Regex matching ``NAME : 'literal' ;`` style rules where
# NAME ends with ``_EDGE``.
_EDGE_OP_RE = re.compile(
    r"^\s*(\w+_EDGE)\s*:\s*'([^']+)'\s*;",
    re.MULTILINE,
)

# Single-quoted literal with a single-character body — punctuation.
_PUNCT_RE = re.compile(
    r"^\s*\w+\s*:\s*'([^'])'\s*;",
    re.MULTILINE,
)


def _parse_grammar(grammar_path: Path) -> GrammarRules:
    """Read ``GVLexer.g4`` and extract keyword / operator /
    punctuation rules.

    Returns a :class:`GrammarRules` populated from whatever the
    parser recognised; falls back to baseline lists for any
    category that came back empty.
    """
    try:
        text = grammar_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return GrammarRules(
            keywords=list(_FALLBACK_KEYWORDS),
            edge_operators=list(_FALLBACK_EDGE_OPERATORS),
            punctuation=list(_FALLBACK_PUNCTUATION),
        )

    # 1. Keywords from ``KW_FOO : F O O ;`` rules.  The fragment
    #    references (``F``, ``O``) just stand for ``[fF]``,
    #    ``[oO]``, etc., so concatenating the captured letters
    #    gives the keyword spelling.
    keywords: list[str] = []
    for m in _KW_RULE_RE.finditer(text):
        letters = m.group(1).split()
        keywords.append("".join(letters).lower())

    # 2. Edge operators: ``DIRECTED_EDGE : '->' ;`` etc.
    edge_operators: list[str] = []
    for m in _EDGE_OP_RE.finditer(text):
        edge_operators.append(m.group(2))

    # 3. Punctuation — single-char string literals (excluding
    #    edge operators which are 2-char).  We collect every
    #    single-quoted single-char token and dedupe.
    punctuation_set: set[str] = set()
    for m in _PUNCT_RE.finditer(text):
        ch = m.group(1)
        # Skip if this is part of a multi-char rule (the regex
        # matches greedily but the body group is single char).
        punctuation_set.add(ch)
    # Filter out characters that overlap with edge operators
    # (e.g. ``-`` on its own would interfere with ``->``).
    punctuation = sorted(
        c for c in punctuation_set
        if not any(c in op for op in edge_operators)
    )

    return GrammarRules(
        keywords=keywords or list(_FALLBACK_KEYWORDS),
        edge_operators=edge_operators or list(_FALLBACK_EDGE_OPERATORS),
        punctuation=punctuation or list(_FALLBACK_PUNCTUATION),
    )


_GRAMMAR_PATH: Path = Path(__file__).parent / "GVLexer.g4"

# Module-level singleton — parsed once; cheap to re-use.
RULES: GrammarRules = _parse_grammar(_GRAMMAR_PATH)


# ─────────────────────────────────────────────────────────────────
# Qt highlighter
# ─────────────────────────────────────────────────────────────────


def _make_highlighter_class():
    """Lazily build the :class:`QSyntaxHighlighter` subclass.

    Importing PyQt6 at module top would force a Qt dependency
    just to inspect the extracted rules — so the Qt-dependent
    code lives inside this factory and only gets invoked when
    a caller actually wants to attach a highlighter to a
    document.
    """
    from PyQt6.QtCore import QRegularExpression
    from PyQt6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat

    # ── Color palette ──
    # Picked to read well on both light backgrounds and the
    # editor's default white background.  Mirrors common
    # editor-theme conventions (Sublime / VS Code light).
    KEYWORD_COLOR = QColor("#0066cc")    # bold blue
    EDGE_OP_COLOR = QColor("#7d3c98")    # bold purple
    PUNCT_COLOR = QColor("#555555")      # dark gray
    STRING_COLOR = QColor("#1f7a1f")     # dark green
    HTML_COLOR = QColor("#b35900")       # dark orange
    HTML_TAG_COLOR = QColor("#7f3300")   # darker orange for < >
    NUMBER_COLOR = QColor("#008080")     # teal
    COMMENT_COLOR = QColor("#888888")    # gray italic
    ATTR_NAME_COLOR = QColor("#aa3300")  # rust — for attr= LHS

    def _fmt(color, bold=False, italic=False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(color)
        if bold:
            f.setFontWeight(QFont.Weight.Bold)
        if italic:
            f.setFontItalic(True)
        return f

    class DotSyntaxHighlighter(QSyntaxHighlighter):
        """Highlights DOT source per the rules extracted from
        ``GVLexer.g4``.

        Attach to a text document in one line::

            highlighter = DotSyntaxHighlighter(editor.document())

        The instance keeps itself alive as long as the document
        does (Qt parents the highlighter to the document).
        """

        # Block-state IDs for multi-line constructs.
        STATE_DEFAULT = 0
        STATE_BLOCK_COMMENT = 1
        STATE_HTML_LABEL = 2

        def __init__(self, parent=None):
            super().__init__(parent)

            # Pre-compile all the simple per-line patterns.  Order
            # matters — the highlighter applies them in sequence
            # and later patterns overwrite earlier ones (used so
            # ``//`` line comments paint over keyword matches).
            self._rules: list[tuple[QRegularExpression, QTextCharFormat]] = []

            kw_fmt = _fmt(KEYWORD_COLOR, bold=True)
            # ``\b`` boundaries make ``graph`` not match ``graphics``.
            # Case-insensitive flag honours the ``KW_*`` rules' case
            # insensitivity in the grammar.
            for kw in RULES.keywords:
                pat = QRegularExpression(
                    r"\b" + re.escape(kw) + r"\b",
                    QRegularExpression.PatternOption.CaseInsensitiveOption,
                )
                self._rules.append((pat, kw_fmt))

            # Edge operators — match longer ones first so ``->``
            # isn't shadowed by ``-``.
            edge_fmt = _fmt(EDGE_OP_COLOR, bold=True)
            for op in sorted(RULES.edge_operators, key=len, reverse=True):
                self._rules.append((
                    QRegularExpression(re.escape(op)),
                    edge_fmt,
                ))

            # Punctuation.
            punct_fmt = _fmt(PUNCT_COLOR)
            for ch in RULES.punctuation:
                self._rules.append((
                    QRegularExpression(re.escape(ch)),
                    punct_fmt,
                ))

            # Numbers (signed int / decimal).  Mirrors
            # ``GVLexer.NUMBER : '-'? ( '.' [0-9]+ |
            # [0-9]+ ( '.' [0-9]* )? );``.
            self._rules.append((
                QRegularExpression(
                    r"-?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)"
                ),
                _fmt(NUMBER_COLOR),
            ))

            # Attribute names on the LHS of ``=`` — colored
            # subtly to make attribute lists scannable.  Match
            # ``\bIDENT\s*=`` and color just the IDENT.
            attr_fmt = _fmt(ATTR_NAME_COLOR)
            self._attr_pattern = QRegularExpression(
                r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*="
            )
            self._attr_fmt = attr_fmt

            # Strings (single-line ``"..."``).  Multi-line
            # strings are unusual in DOT but possible if a label
            # contains a literal newline; we treat each line of a
            # multi-line string as starting fresh, which mis-
            # colors the tail.  Acceptable for an editor preview.
            self._string_pattern = QRegularExpression(
                r'"(?:\\.|[^"\\])*"'
            )
            self._string_fmt = _fmt(STRING_COLOR)

            # ``//`` line comments + ``#`` preprocessor lines.
            self._line_comment_pattern = QRegularExpression(
                r"(?://|#)[^\n]*"
            )
            self._line_comment_fmt = _fmt(COMMENT_COLOR, italic=True)

            # ``/* ... */`` block comments — multi-line tracked
            # via blockState.
            self._block_comment_start = QRegularExpression(r"/\*")
            self._block_comment_end = QRegularExpression(r"\*/")
            self._block_comment_fmt = _fmt(COMMENT_COLOR, italic=True)

            # HTML labels: ``<...>``.  Single-line only;
            # multi-line nested HTML rarely appears.
            self._html_pattern = QRegularExpression(r"<[^>]*>")
            self._html_fmt = _fmt(HTML_COLOR)
            self._html_tag_fmt = _fmt(HTML_TAG_COLOR, bold=True)

        # ── highlightBlock — called by Qt for every text block ──
        def highlightBlock(self, text: str) -> None:
            # 1. Apply simple per-line rules in order.
            for pattern, fmt in self._rules:
                it = pattern.globalMatch(text)
                while it.hasNext():
                    m = it.next()
                    self.setFormat(m.capturedStart(), m.capturedLength(), fmt)

            # 2. Attribute-name LHS — color just the captured group.
            it = self._attr_pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(
                    m.capturedStart(1),
                    m.capturedLength(1),
                    self._attr_fmt,
                )

            # 3. String literals (single-line) — overwrite any
            #    previous coloring inside.
            it = self._string_pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(
                    m.capturedStart(),
                    m.capturedLength(),
                    self._string_fmt,
                )

            # 4. HTML labels (single-line) — overwrite contents.
            it = self._html_pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                start = m.capturedStart()
                length = m.capturedLength()
                self.setFormat(start, length, self._html_fmt)
                # Recolor the angle brackets themselves with
                # the bold tag color.
                self.setFormat(start, 1, self._html_tag_fmt)
                self.setFormat(start + length - 1, 1, self._html_tag_fmt)

            # 5. Line comments — last so they overwrite anything
            #    on the comment portion of the line.
            it = self._line_comment_pattern.globalMatch(text)
            while it.hasNext():
                m = it.next()
                self.setFormat(
                    m.capturedStart(),
                    m.capturedLength(),
                    self._line_comment_fmt,
                )

            # 6. Block comments — span across lines via
            #    blockState.
            self.setCurrentBlockState(self.STATE_DEFAULT)
            start_index = 0
            if self.previousBlockState() != self.STATE_BLOCK_COMMENT:
                start_match = self._block_comment_start.match(text, 0)
                start_index = (
                    start_match.capturedStart()
                    if start_match.hasMatch() else -1
                )
            while start_index >= 0:
                end_match = self._block_comment_end.match(text, start_index)
                if not end_match.hasMatch():
                    # Comment spans past end-of-block; mark
                    # state and color from start_index to end.
                    self.setCurrentBlockState(self.STATE_BLOCK_COMMENT)
                    length = len(text) - start_index
                    self.setFormat(
                        start_index, length, self._block_comment_fmt
                    )
                    break
                length = (
                    end_match.capturedEnd() - start_index
                )
                self.setFormat(
                    start_index, length, self._block_comment_fmt
                )
                # Look for another block-comment start after this one.
                start_match = self._block_comment_start.match(
                    text, end_match.capturedEnd()
                )
                start_index = (
                    start_match.capturedStart()
                    if start_match.hasMatch() else -1
                )

    return DotSyntaxHighlighter


def DotSyntaxHighlighter(parent=None):  # noqa: N802 — class-style factory
    """Return a fresh :class:`QSyntaxHighlighter` attached to
    ``parent`` (a ``QTextDocument`` or ``QObject``).

    Implemented as a factory function so the Qt import cost is
    deferred until the caller actually wants a highlighter
    instance — module-level imports of ``dot_highlighter`` (e.g.
    in tests that just inspect ``RULES``) don't trigger Qt.
    """
    cls = _make_highlighter_class()
    return cls(parent)
