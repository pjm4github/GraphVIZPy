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

    def compute_size(self, fontsize: float = 14.0,
                     char_width_factor: float = 0.52,
                     field_pad: float = 8.0,
                     min_cell: float = 20.0):
        """Compute natural width/height for this field tree.

        Matches C lib/common/shapes.c size_reclbl() logic:
        - Leaf fields: sized by text content
        - Container fields: children are laid out LR or TB
        - Each nesting level alternates direction

        After this call, every field in the tree has width/height set
        to its natural size (before fitting to node bounds).

        Args:
            fontsize: Font size in points.
            char_width_factor: Approximate char width as fraction of fontsize.
            field_pad: Horizontal padding per field (points).
            min_cell: Minimum cell dimension (points).
        """
        char_w = fontsize * char_width_factor
        cell_h = fontsize * 1.4 + 4.0

        if self.is_leaf:
            text_w = len(self.text) * char_w + field_pad * 2
            self.width = max(text_w, min_cell)
            self.height = cell_h
            return

        # Compute children sizes first
        for child in self.children:
            child.compute_size(fontsize, char_width_factor,
                               field_pad, min_cell)

        if self.LR:
            # Children arranged left-to-right
            self.width = sum(c.width for c in self.children)
            self.height = max((c.height for c in self.children),
                              default=cell_h)
        else:
            # Children arranged top-to-bottom
            self.width = max((c.width for c in self.children),
                             default=min_cell)
            self.height = sum(c.height for c in self.children)

    def compute_positions(self, x: float = 0.0, y: float = 0.0,
                          total_w: float = 0.0, total_h: float = 0.0):
        """Assign x, y positions to each field in the tree.

        Distributes children proportionally within the given bounds,
        matching C lib/common/shapes.c size_reclbl() + pos_reclbl().

        Args:
            x, y: Top-left corner of this field's region.
            total_w, total_h: Available width/height for this field.
                If 0, uses self.width/self.height (natural size).
        """
        if total_w <= 0:
            total_w = self.width
        if total_h <= 0:
            total_h = self.height

        self.x = x
        self.y = y
        self.width = total_w
        self.height = total_h

        if self.is_leaf or not self.children:
            return

        # Distribute children proportionally
        if self.LR:
            # Left-to-right: divide width proportionally
            natural_total = sum(c.width for c in self.children)
            cx = x
            for child in self.children:
                if natural_total > 0:
                    frac = child.width / natural_total
                else:
                    frac = 1.0 / len(self.children)
                cw = frac * total_w
                child.compute_positions(cx, y, cw, total_h)
                cx += cw
        else:
            # Top-to-bottom: divide height proportionally
            natural_total = sum(c.height for c in self.children)
            cy = y
            for child in self.children:
                if natural_total > 0:
                    frac = child.height / natural_total
                else:
                    frac = 1.0 / len(self.children)
                ch = frac * total_h
                child.compute_positions(x, cy, total_w, ch)
                cy += ch

    def port_position(self, port_name: str) -> Optional[tuple]:
        """Return (center_x, center_y) of a port within this field tree.

        Returns None if port not found.  Coordinates are relative to
        the field tree's top-left corner.
        """
        f = self.find_port(port_name)
        if f is None:
            return None
        return (f.x + f.width / 2.0, f.y + f.height / 2.0)

    def port_fraction(self, port_name: str) -> Optional[float]:
        """Return the port's horizontal position as a fraction [0..1].

        Used for port.order computation in mincross
        (C sameport.c:151-152).  Returns None if port not found.
        """
        f = self.find_port(port_name)
        if f is None:
            return None
        if self.width <= 0:
            return 0.5
        return (f.x + f.width / 2.0 - self.x) / self.width


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
