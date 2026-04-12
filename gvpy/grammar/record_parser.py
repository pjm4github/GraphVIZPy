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
                     min_cell: float = 20.0):
        """Compute natural width/height for this field tree.

        Matches C lib/common/shapes.c:3526-3569 size_reclbl() logic:
        - Leaf fields with text: sized by text content + PAD
          (XPAD=4*GAP=16pt, YPAD=2*GAP=8pt; macros.h:27-29, const.h:251)
        - Leaf fields without text (empty ports): size={0,0}
        - Container fields: children are laid out LR or TB
        - Each nesting level alternates direction

        After this call, every field in the tree has width/height set
        to its natural size (before fitting to node bounds).

        Args:
            fontsize: Font size in points.
            char_width_factor: Fallback char width factor if font
                metrics unavailable (fraction of fontsize).
            min_cell: Minimum cell dimension (points).
        """
        # Use system font metrics (tkinter/GDI+) when available,
        # fall back to Times-Roman AFM, then to char_width_factor.
        # C uses the system font engine for exact text dimensions.
        _text_width_fn = None
        try:
            from gvpy.engines.font_metrics import text_width_system
            # Test once to see if tkinter works
            if text_width_system("x", fontsize) is not None:
                _text_width_fn = lambda t: text_width_system(t, fontsize)
        except ImportError:
            pass
        if _text_width_fn is None:
            try:
                from gvpy.engines.font_metrics import text_width_times_roman
                _text_width_fn = lambda t: text_width_times_roman(t, fontsize)
            except ImportError:
                pass

        # C PAD values (macros.h:27-29, const.h:251 GAP=4):
        # XPAD = 4*GAP = 16pt, YPAD = 2*GAP = 8pt
        _XPAD = 16.0  # 4 * GAP
        _YPAD = 8.0    # 2 * GAP

        if self.is_leaf:
            # C size_reclbl (shapes.c:3534-3552):
            # if f->lp: dimen = f->lp->dimen; if dimen > 0: PAD(dimen)
            #
            # C parse_reclbl (shapes.c:3460-3462): empty port fields
            # (no text, no sub-table) get a space character inserted:
            #   if (!(mode & (HASTEXT | HASTABLE))) { *tsp++ = ' '; }
            # So make_label receives " ", giving non-zero font dims.
            # The space label has width > 0, height > 0, so PAD applies.
            #
            # Text height from font engine: C's textspan_size returns
            # the line height, which is typically fontsize * 1.2 for
            # standard PostScript fonts. For 14pt → 16.8pt line height.
            # (Measured against instrumented C: 14 * 1.2 + 8 = 24.8)
            _LINE_HEIGHT_FACTOR = 1.2
            effective_text = self.text if self.text else " "
            text_h = fontsize * _LINE_HEIGHT_FACTOR
            if _text_width_fn:
                text_w = _text_width_fn(effective_text)
            else:
                char_w = fontsize * char_width_factor
                text_w = len(effective_text) * char_w
            # Apply PAD (C: PAD(dimen) → dimen.x += XPAD, dimen.y += YPAD)
            self.width = text_w + _XPAD
            self.height = text_h + _YPAD
            return

        # Compute children sizes first
        for child in self.children:
            child.compute_size(fontsize, char_width_factor, min_cell)

        # C size_reclbl (shapes.c:3556-3567): aggregate children
        if self.LR:
            # Children arranged left-to-right
            self.width = sum(c.width for c in self.children)
            self.height = max((c.height for c in self.children),
                              default=0.0)
        else:
            # Children arranged top-to-bottom
            self.width = max((c.width for c in self.children),
                             default=0.0)
            self.height = sum(c.height for c in self.children)

    def resize(self, new_w: float, new_h: float):
        """Fit field tree to given bounds, distributing excess space.

        Matches C lib/common/shapes.c:3571-3606 resize_reclbl().
        After compute_size() gives natural dimensions, this method
        redistributes the difference (new_size - natural_size) evenly
        across children using integer arithmetic to avoid gaps.

        Args:
            new_w: Target width for this field.
            new_h: Target height for this field.
        """
        # C resize_reclbl (shapes.c:3573-3575):
        # d.x = sz.x - f->size.x; d.y = sz.y - f->size.y; f->size = sz;
        dx = new_w - self.width
        dy = new_h - self.height
        self.width = new_w
        self.height = new_h

        if not self.children:
            return

        # C resize_reclbl (shapes.c:3588-3603):
        # Distribute delta evenly across children.
        # Uses integer arithmetic: amt = floor((i+1)*inc) - floor(i*inc)
        n = len(self.children)
        if self.LR:
            inc = dx / n
            for i, child in enumerate(self.children):
                amt = int((i + 1) * inc) - int(i * inc)
                child.resize(child.width + amt, new_h)
        else:
            inc = dy / n
            for i, child in enumerate(self.children):
                amt = int((i + 1) * inc) - int(i * inc)
                child.resize(new_w, child.height + amt)

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

    def port_fraction(self, port_name: str,
                      rankdir: int = 0) -> Optional[float]:
        """Return the port.order as a fraction [0..1] of MC_SCALE.

        Matches C compassPort's pipeline (shapes.c:2856-2872):

            p = mid_pointf(sub_field.b.LL, sub_field.b.UR)
            p = cwrotatepf(p, 90 * GD_rankdir)
            angle = atan2(p.y, p.x) + 1.5*PI
            if angle >= 2*PI: angle -= 2*PI
            port.order = (int)(MC_SCALE * angle / (2*PI))

        Where (p.x, p.y) is the port center in node-local coordinates
        with y-axis UP (math convention), then rotated clockwise by
        90° × rankdir to account for LR/BT/RL rankdir.

        Args:
            port_name: The port identifier to look up.
            rankdir: Graphviz rankdir constant — 0=TB, 1=LR, 2=BT, 3=RL.
                Corresponds to C's GD_rankdir return value.

        The resulting order places the port on a "compass" around the
        node center: North=0, West=64, South=128, East=192 (for
        MC_SCALE=256). Going CCW from North (math convention) the
        order increases.

        NOTE: The field tree must already be in the pre-rotation
        layout for the given rankdir (i.e., for LR/RL, caller has
        invoked _flip_record_lr before compute_size). This method
        then applies the same cwrotate that C's compassPort does.
        """
        import math
        f = self.find_port(port_name)
        if f is None:
            return None

        # Compute port center in node-local math coordinates
        # (y up, origin at root center).
        # Python positions use top-left origin with y down;
        # convert: node_y_math = root.cy - field_y_python
        root_cx = self.x + self.width / 2.0
        root_cy = self.y + self.height / 2.0
        px = (f.x + f.width / 2.0) - root_cx
        # Invert y to math convention (y up)
        py = root_cy - (f.y + f.height / 2.0)

        # Apply cwrotate(90 * rankdir) — C shapes.c:2856
        # cwrotate 90°:  (x,y) → (y, -x)
        # cwrotate 180°: (x,y) → (x, -y)
        # cwrotate 270°: (x,y) → (y,  x)  (exch_xy)
        cwrot = 90 * (rankdir % 4)
        if cwrot == 90:
            px, py = py, -px
        elif cwrot == 180:
            py = -py
        elif cwrot == 270:
            px, py = py, px

        # Angle-based port.order (C shapes.c:2864-2872)
        if px == 0.0 and py == 0.0:
            return 0.5
        angle = math.atan2(py, px) + 1.5 * math.pi
        if angle >= 2.0 * math.pi:
            angle -= 2.0 * math.pi
        return angle / (2.0 * math.pi)


class _RecordVisitor(RecordParserVisitor):
    """ANTLR4 visitor that builds a RecordField tree."""

    def __init__(self, top_lr: bool = True):
        self._lr = top_lr  # current LR direction (alternates)

    def visitRecordLabel(self, ctx: RecordParser.RecordLabelContext):
        """Top-level: may have outer braces or bare.

        C shapes.c parse_reclbl: The FIRST call to parse_reclbl starts
        with LR=flip. If the label starts with `{`, that `{` triggers
        a recursive call with !LR (shapes.c:3446). So an outer `{...}`
        effectively inverts the top-level LR direction.

        Our ANTLR grammar consumes the outer LBRACE in the recordLabel
        rule (not as a separate field), so we need to apply that
        same LR inversion here to match C's structure.
        """
        if ctx.LBRACE():
            # Outer braces cause LR alternation (matching C's recursion)
            saved_lr = self._lr
            self._lr = not self._lr
            result = self.visitFieldList(ctx.fieldList())
            self._lr = saved_lr
            return result
        return self.visitFieldList(ctx.fieldList())

    def visitFieldList(self, ctx: RecordParser.FieldListContext):
        """field ('|' field)* → RecordField with children.

        Creates a container with the CURRENT self._lr value.
        C parse_reclbl does not do single-child unwrapping — it
        preserves the structure exactly as parsed.
        """
        fields = []
        for field_ctx in ctx.field():
            fields.append(self.visitField(field_ctx))
        return RecordField(LR=self._lr, children=fields)

    def visitField(self, ctx: RecordParser.FieldContext):
        """Single field: nested sub-record or leaf."""
        if ctx.fieldList():
            # Nested: { fieldList } — alternate LR direction
            # C shapes.c:3446: parse_reclbl(n, !LR, false, text)
            # The nested container is created with the FLIPPED LR,
            # so its own LR is the opposite of the parent's.
            saved_lr = self._lr
            self._lr = not self._lr
            result = self.visitFieldList(ctx.fieldList())
            # result.LR is set by visitFieldList using self._lr (the
            # flipped value), so the container correctly has !saved_lr.
            self._lr = saved_lr  # restore for siblings
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
