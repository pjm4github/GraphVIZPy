"""Node shape primitives — bounding box + inside tests + self-loop arc.

See: /lib/common/geom.h @ 41         (Box struct)
See: /lib/common/splines.c @ 109     (ellipse_inside / box_inside dispatch)
See: /lib/common/splines.c @ 1164    (self-loop arc control points)

Engine-agnostic: the dataclass, inside-test closures, and self-loop
helper touch only primitive coordinates, so any layout engine can pull
them in.  ``dot/path.py``, ``dot/clip.py``, and ``dot/splines.py``
re-export for back-compat so existing imports keep working.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from gvpy.engines.layout.common.geom import Ppoint


# ── Box ──────────────────────────────────────────────────────────────

@dataclass
class Box:
    """Axis-aligned 2D bounding box.

    See: /lib/common/geom.h @ 41

    Mutable so routers can widen a box in place (e.g. dot's
    ``adjustregularpath`` stretches edges to meet ``MINW``).
    """

    ll_x: float = 0.0
    ll_y: float = 0.0
    ur_x: float = 0.0
    ur_y: float = 0.0

    @property
    def width(self) -> float:
        return self.ur_x - self.ll_x

    @property
    def height(self) -> float:
        return self.ur_y - self.ll_y

    def is_valid(self) -> bool:
        """True iff ``ll`` is strictly below-and-left of ``ur``.

        See: /lib/common/geom.h @ 41
        """
        return self.ll_x < self.ur_x and self.ll_y < self.ur_y


# ── Inside-test helpers ──────────────────────────────────────────────

InsideFn = Callable[[Ppoint], bool]


def ellipse_inside(hw: float, hh: float) -> InsideFn:
    """Inside-test for an axis-aligned ellipse centred at origin.

    *hw* and *hh* are the half-width and half-height.  Uses the
    standard ``(x/hw)^2 + (y/hh)^2 <= 1`` form.
    """
    def _inside(p: Ppoint) -> bool:
        if hw <= 0 or hh <= 0:
            return False
        return (p.x / hw) ** 2 + (p.y / hh) ** 2 <= 1.0
    return _inside


def box_inside(hw: float, hh: float) -> InsideFn:
    """Inside-test for an axis-aligned rectangle centred at origin."""
    def _inside(p: Ppoint) -> bool:
        return abs(p.x) <= hw and abs(p.y) <= hh
    return _inside


def make_inside_fn(shape: str, hw: float, hh: float) -> InsideFn:
    """Build a node-boundary inside-test from shape name and half-sizes.

    Replaces C's ``ND_shape(n)->fns->insidefn`` callback.  Currently
    handles ``ellipse`` (default) and the ``box`` / ``rect`` family.
    Other shapes fall back to ellipse.
    """
    s = (shape or "").lower()
    if s in ("box", "rect", "rectangle", "square",
             "record", "mrecord", "plaintext", "plain",
             "none", "underline", "tab", "folder",
             "component", "note", "signature", "rpromoter",
             "rarrow", "larrow", "lpromoter",
             "cds", "promoter", "terminator",
             "utr", "primersite", "restrictionsite",
             "fivepoverhang", "threepoverhang",
             "noverhang", "assembly", "insulator",
             "ribosite", "rnastab", "proteasesite",
             "proteinstab"):
        return box_inside(hw, hh)
    return ellipse_inside(hw, hh)


# ── Self-loop arc ────────────────────────────────────────────────────

def self_loop_points(ln: Any) -> list[tuple[float, float]]:
    """Four control points for a small self-loop arc anchored to ``ln``.

    See: /lib/common/splines.c @ 1164

    Takes any object with ``.x``, ``.y``, ``.width`` attributes — all
    engine ``LayoutNode`` classes satisfy this duck-typed contract.
    Returns the cubic-bezier control polygon for a 20pt rightward arc.
    """
    hw = ln.width / 2.0
    loop = 20.0
    return [
        (ln.x + hw, ln.y),
        (ln.x + hw + loop, ln.y - loop),
        (ln.x + hw + loop, ln.y + loop),
        (ln.x + hw, ln.y),
    ]
