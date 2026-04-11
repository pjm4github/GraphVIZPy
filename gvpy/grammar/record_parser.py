"""Record label parser for Graphviz Mrecord/record node shapes.

Parses labels like ``{name|{<In0>|<In1>}|fmap|{<Out0>}}`` into a
structured field tree.  Uses the ANTLR4-generated RecordLexer/RecordParser.

C reference: lib/common/shapes.c parse_reclbl()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from antlr4 import CommonTokenStream, InputStream

from .generated.RecordLexer import RecordLexer
from .generated.RecordParser import RecordParser
from .generated.RecordParserVisitor import RecordParserVisitor


@dataclass
class RecordField:
    """One field in a record label tree.

    Mirrors C ``field_t`` (lib/common/shapes.c:115-128).

    A field is either:
    - A leaf: has ``text`` and optional ``port``
    - A container: has ``children`` (sub-fields) and ``LR`` direction

    After sizing, ``x``, ``y``, ``width``, ``height`` hold the
    field's position relative to the node center.
    """
    text: str = ""              # Display text (C: field_t.lp->text)
    port: str = ""              # Port name if <port> specified
    children: list[RecordField] = field(default_factory=list)
    LR: bool = True             # True = left-to-right, False = top-to-bottom
                                # (C: field_t.LR — alternates at each nesting)

    # Computed during sizing (C: field_t.b = bounding box)
    x: float = 0.0             # Position relative to node center
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def find_port(self, port_name: str) -> Optional[RecordField]:
        """Find the field with the given port name (recursive)."""
        if self.port == port_name:
            return self
        for child in self.children:
            found = child.find_port(port_name)
            if found is not None:
                return found
        return None

    def leaf_count(self) -> int:
        """Count total leaf fields (recursive)."""
        if self.is_leaf:
            return 1
        return sum(c.leaf_count() for c in self.children)


class _RecordVisitor(RecordParserVisitor):
    """ANTLR4 visitor that builds a RecordField tree."""

    def __init__(self, top_lr: bool = True):
        self._lr = top_lr  # current LR direction (alternates)

    def visitRecordLabel(self, ctx: RecordParser.RecordLabelContext):
        """Top-level: may have outer braces or bare."""
        return self.visitFieldList(ctx.fieldList())

    def visitFieldList(self, ctx: RecordParser.FieldListContext):
        """field ('|' field)* → RecordField with children."""
        fields = []
        for field_ctx in ctx.field():
            fields.append(self.visitField(field_ctx))

        if len(fields) == 1 and fields[0].children:
            # Single nested sub-record — unwrap
            return fields[0]

        container = RecordField(LR=self._lr, children=fields)
        return container

    def visitField(self, ctx: RecordParser.FieldContext):
        """Single field: nested sub-record or leaf."""
        if ctx.fieldList():
            # Nested: { fieldList } — alternate LR direction
            # (C parse_reclbl: parse_reclbl(n, !LR, false, text))
            saved_lr = self._lr
            self._lr = not self._lr
            result = self.visitFieldList(ctx.fieldList())
            result.LR = saved_lr  # container uses parent's LR
            self._lr = saved_lr
            # The children alternate
            for child in result.children:
                child.LR = not saved_lr
            return result

        # Leaf field: optional port + text
        port_name = ""
        if ctx.port():
            port_ctx = ctx.port()
            pn_ctx = port_ctx.portName()
            if pn_ctx:
                port_name = pn_ctx.getText().strip()

        text_parts = []
        for tc in ctx.textContent():
            text_parts.append(tc.getText())
        text = "".join(text_parts).strip()

        return RecordField(text=text, port=port_name, LR=self._lr)


def parse_record_label(label: str, LR: bool = True) -> RecordField:
    """Parse a Graphviz record label string into a RecordField tree.

    Args:
        label: The record label, e.g. ``{name|In|{<Out0>|<Out1>}}``
        LR: Initial direction. True for left-to-right fields,
            False for top-to-bottom.  Alternates at each nesting.
            For ``rankdir=LR``, the initial direction is flipped
            by the caller (C: shapes.c:3705 ``flip``).

    Returns:
        Root RecordField with children representing the field tree.

    C reference: lib/common/shapes.c:3382 parse_reclbl()
    """
    if not label or not label.strip():
        return RecordField(text=label or "", LR=LR)

    input_stream = InputStream(label)
    lexer = RecordLexer(input_stream)
    lexer.removeErrorListeners()  # suppress ANTLR error output
    stream = CommonTokenStream(lexer)
    parser = RecordParser(stream)
    parser.removeErrorListeners()

    tree = parser.recordLabel()
    visitor = _RecordVisitor(top_lr=LR)
    result = visitor.visit(tree)

    if result is None:
        return RecordField(text=label, LR=LR)

    return result
