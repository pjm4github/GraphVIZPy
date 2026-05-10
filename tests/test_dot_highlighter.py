"""Tests for the grammar-driven DOT syntax highlighter."""
from __future__ import annotations

import pytest

from gvpy.grammar.dot_highlighter import (
    GrammarRules,
    RULES,
    _parse_grammar,
    _FALLBACK_KEYWORDS,
    _FALLBACK_EDGE_OPERATORS,
    _FALLBACK_PUNCTUATION,
)


class TestGrammarParsing:
    """The grammar parser reads ``GVLexer.g4`` and extracts
    keyword / edge-operator / punctuation rules."""

    def test_default_rules_loaded_from_grammar_file(self):
        """At module load, ``RULES`` is populated from
        ``GVLexer.g4``."""
        assert isinstance(RULES, GrammarRules)
        # The current grammar defines exactly these 6 keywords.
        assert sorted(RULES.keywords) == sorted([
            "strict", "graph", "digraph",
            "node", "edge", "subgraph",
        ])

    def test_edge_operators_extracted(self):
        """``DIRECTED_EDGE`` and ``UNDIRECTED_EDGE`` rules
        produce ``->`` and ``--``."""
        assert "->" in RULES.edge_operators
        assert "--" in RULES.edge_operators

    def test_punctuation_extracted(self):
        """All 8 single-char punctuation rules are recognised."""
        for ch in ("{", "}", "[", "]", ";", ",", ":", "="):
            assert ch in RULES.punctuation, f"missing {ch!r}"

    def test_punctuation_excludes_edge_operator_chars(self):
        """``-`` is part of ``->`` / ``--`` so it must not show
        up as standalone punctuation (would mis-color)."""
        assert "-" not in RULES.punctuation

    def test_fallback_when_grammar_missing(self, tmp_path):
        """If the grammar file is unreadable, fall back to the
        baseline lists."""
        nonexistent = tmp_path / "no-such-file.g4"
        rules = _parse_grammar(nonexistent)
        assert rules.keywords == _FALLBACK_KEYWORDS
        assert rules.edge_operators == _FALLBACK_EDGE_OPERATORS
        assert rules.punctuation == _FALLBACK_PUNCTUATION

    def test_grammar_parser_handles_arbitrary_keywords(
        self, tmp_path,
    ):
        """A grammar with new keywords parses to those new
        keywords (verifies the parser isn't hardcoded)."""
        g4 = tmp_path / "test.g4"
        g4.write_text(
            "lexer grammar Test;\n"
            "fragment X: [xX]; fragment Y: [yY]; fragment Z: [zZ];\n"
            "KW_XYZ : X Y Z ;\n"
            "ARROW_EDGE : '=>';\n"
            "LBRACE : '{' ;\n",
            encoding="utf-8",
        )
        rules = _parse_grammar(g4)
        assert "xyz" in rules.keywords
        assert "=>" in rules.edge_operators
        assert "{" in rules.punctuation


class TestHighlighter:
    """The QSyntaxHighlighter applies the rules to a Qt
    document.  Skipped if Qt isn't available."""

    @pytest.fixture
    def app(self):
        """Headless QApplication for highlighter tests."""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PyQt6.QtWidgets import QApplication
        except ImportError:
            pytest.skip("PyQt6 not available")
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    def _highlights(self, app, text: str):
        """Run the highlighter on ``text`` and return a list of
        ``(start, length, color_name)`` triples for every
        formatted span on the first block.

        We use Qt's text-document machinery to run the
        highlighter, then walk the formatted ranges.
        """
        from PyQt6.QtGui import QTextDocument
        from gvpy.grammar.dot_highlighter import DotSyntaxHighlighter
        doc = QTextDocument()
        doc.setPlainText(text)
        h = DotSyntaxHighlighter(doc)
        # Force re-highlight to ensure formats are applied.
        h.rehighlight()
        # Walk every block and collect formatted spans.
        spans = []
        block = doc.firstBlock()
        while block.isValid():
            offset = block.position()
            for fr in block.layout().formats():
                fmt = fr.format
                color = fmt.foreground().color()
                spans.append((
                    offset + fr.start, fr.length,
                    color.name(),
                ))
            block = block.next()
        return spans

    def test_keyword_highlighted(self, app):
        spans = self._highlights(app, "digraph G { }")
        # ``digraph`` should be at offset 0 with length 7,
        # colored with the keyword color (#0066cc).
        kw_spans = [s for s in spans if s[2] == "#0066cc"]
        assert any(s[0] == 0 and s[1] == 7 for s in kw_spans), (
            f"digraph keyword not highlighted: {spans}"
        )

    def test_edge_operator_highlighted(self, app):
        spans = self._highlights(app, "a -> b")
        # ``->`` at offset 2 length 2, edge-op color (#7d3c98).
        ops = [s for s in spans if s[2] == "#7d3c98"]
        assert any(s[0] == 2 and s[1] == 2 for s in ops), (
            f"-> operator not highlighted: {spans}"
        )

    def test_string_literal_highlighted(self, app):
        spans = self._highlights(app, 'a [label="hi"]')
        # The full ``"hi"`` (offset 9, length 4) gets the
        # string color (#1f7a1f).
        strs = [s for s in spans if s[2] == "#1f7a1f"]
        assert any(
            s[0] == 9 and s[1] == 4 for s in strs
        ), f"string literal not highlighted: {spans}"

    def test_line_comment_highlighted(self, app):
        spans = self._highlights(app, "graph { // hello\n}")
        # ``// hello`` from offset 8 to end-of-line gets the
        # comment color (#888888).
        comments = [s for s in spans if s[2] == "#888888"]
        assert comments, f"line comment not highlighted: {spans}"

    def test_number_highlighted(self, app):
        spans = self._highlights(app, "a [width=1.5]")
        # ``1.5`` gets the number color (#008080).
        nums = [s for s in spans if s[2] == "#008080"]
        # Either a single 3-char span (1.5) or the parser may
        # split — just assert at least one teal span exists.
        assert nums, f"number not highlighted: {spans}"

    def test_attribute_name_highlighted(self, app):
        spans = self._highlights(app, "a [color=red]")
        # ``color`` (offset 3, length 5) gets the attr-name
        # color (#aa3300).  Note: ``color`` itself isn't a
        # keyword, so the rule only matches the attribute LHS.
        attrs = [s for s in spans if s[2] == "#aa3300"]
        assert any(s[0] == 3 and s[1] == 5 for s in attrs), (
            f"attribute name not highlighted: {spans}"
        )

    def test_html_label_highlighted(self, app):
        spans = self._highlights(
            app, 'a [label=<<b>hi</b>>]'
        )
        # The outer ``<...>`` gets the html color (#b35900).
        html = [s for s in spans if s[2] == "#b35900"]
        assert html, f"HTML label not highlighted: {spans}"

    def test_block_comment_multi_line(self, app):
        text = "/* line1\nline2 */ graph { }"
        spans = self._highlights(app, text)
        comments = [s for s in spans if s[2] == "#888888"]
        # Both lines of the block comment should have at least
        # one comment-colored span.
        assert any(s[0] < 8 for s in comments)
        assert any(s[0] >= 9 for s in comments)
