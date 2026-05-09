"""C-aligned port of the rectangle packer in ``lib/pack/pack.c``
that osage relies on.

We only port the entry points osage actually uses:

- :func:`array_rects` — the workhorse for ``packmode=array`` (the
  osage default).  Mirrors C ``arrayRects`` (pack.c:604).
- :func:`put_rects` — top-level dispatcher.  Mirrors C
  ``putRects`` (pack.c:930).
- :func:`parse_pack_mode` — parse ``packmode`` attribute string
  into a :class:`PackInfo`.  Mirrors C ``parsePackModeInfo``
  (pack.c:1211).
- :func:`get_pack_info` — combine ``pack`` (margin) + ``packmode``
  (mode/flags/size) attribute reads.  Mirrors C ``getPackInfo``
  (pack.c:1284).

The other modes (``polyRects`` for ``l_graph`` / polyomino
packing, ``aspectRects`` for ``l_aspect``) are out of scope —
osage only ever requests ``l_array`` and falls through to
``l_graph`` for ``l_node`` / ``l_clust`` (which then renders via
polyomino packing).  GraphvizPy's osage uses ``l_array`` only;
fdp/sfdp's component packing has its own polyomino implementation
in :mod:`gvpy.engines.layout.neato._neato_pack`.

Algorithm (mirrors C verbatim):

1. **Grid sizing.**  ``ceil(sqrt(n))`` columns by default; if
   ``packmode=array<size>`` was given, that's the column count
   (row count for ``_c`` col-major).
2. **Sort.**
   - If ``PK_USER_VALS`` flag set, sort ascending by user-supplied
     ``packval`` (typically read from the ``sortv`` attribute).
   - Else if no ``PK_INPUT_ORDER`` flag, sort *descending* by
     ``width + height`` — biggest rectangles first.
   - Else preserve input order.
3. **Per-cell sizing.**  ``widths[c] = max(rect.width)`` over
   rects assigned to column ``c``.  ``heights[r]`` similarly.
4. **Cumulative positions.**  ``widths[i] = Σ widths[0..i-1]``
   (prefix sum).  ``heights`` is built in *reverse* — row 0 is at
   the top of the layout.  This subtle row-reversal mirrors C
   verbatim and is what gives osage's "sortv-low at top-left,
   sortv-high at bottom-right" reading order.
5. **Place each rect inside its cell.**  Per-axis alignment via
   the ``PK_*_ALIGN`` flags (defaults to centered).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# Mirror C enums and flag bits (pack.h)
# ─────────────────────────────────────────────────────────────────


class PackMode(IntEnum):
    """Mirrors C ``pack_mode`` (pack.h).  Only ``l_array`` is
    actually used by osage; ``l_graph`` is the fallback that
    polyomino packing handles in C.  Other modes are listed for
    completeness when parsing the ``packmode`` attribute."""

    L_UNDEF = 0
    L_NODE = 1
    L_CLUST = 2
    L_ARRAY = 3
    L_ASPECT = 4
    L_GRAPH = 5


# Flags from pack.h.  These match C's bit layout.
PK_COL_MAJOR: int = 1 << 0     # iterate column-by-column not row-by-row
PK_INPUT_ORDER: int = 1 << 1   # don't sort
PK_USER_VALS: int = 1 << 2     # sort by user-supplied values
PK_LEFT_ALIGN: int = 1 << 3    # x-align rectangles left in cell
PK_RIGHT_ALIGN: int = 1 << 4   # x-align rectangles right in cell
PK_TOP_ALIGN: int = 1 << 5     # y-align rectangles top in cell
PK_BOT_ALIGN: int = 1 << 6     # y-align rectangles bottom in cell


# Default margin from osage/osageinit.c:34.
DFLT_MARGIN: int = 8


# ─────────────────────────────────────────────────────────────────
# pack_info-equivalent
# ─────────────────────────────────────────────────────────────────


@dataclass
class PackInfo:
    """Mirrors C ``pack_info`` (pack.h).

    Attributes are written in the order osage reads them — first
    ``getPackInfo`` populates ``margin`` from the ``pack`` graph
    attribute, then ``parsePackModeInfo`` populates ``mode``,
    ``sz``, ``flags``, and ``aspect`` from ``packmode``, leaving
    ``vals`` for the caller to supply later (osage reads
    per-cluster ``sortv`` and per-node ``sortv`` when
    ``PK_USER_VALS`` is set).
    """

    margin: int = DFLT_MARGIN
    mode: PackMode = PackMode.L_ARRAY
    sz: int = 0                 # cols (rows in col-major); 0 → auto sqrt
    flags: int = 0              # PK_* bitfield
    aspect: float = 1.0         # for l_aspect mode (unused in osage)
    vals: Optional[list[int]] = None  # user values (sortv)


# ─────────────────────────────────────────────────────────────────
# packmode parsing
# ─────────────────────────────────────────────────────────────────


def _chk_flags(suffix: str, info: PackInfo) -> str:
    """Mirrors C ``chkFlags`` (pack.c:1143).

    Consumes optional ``_<flags>`` directly after the mode word.
    Each flag is one of: ``c i u t b l r``.  Returns the leftover
    suffix after flag chars (which may then encode the size).
    """
    if not suffix.startswith("_"):
        return suffix
    p = suffix[1:]
    flag_map = {
        "c": PK_COL_MAJOR,
        "i": PK_INPUT_ORDER,
        "u": PK_USER_VALS,
        "t": PK_TOP_ALIGN,
        "b": PK_BOT_ALIGN,
        "l": PK_LEFT_ALIGN,
        "r": PK_RIGHT_ALIGN,
    }
    while p and p[0] in flag_map:
        info.flags |= flag_map[p[0]]
        p = p[1:]
    return p


def parse_pack_mode(
    spec: Optional[str],
    default: PackMode = PackMode.L_ARRAY,
) -> PackInfo:
    """Mirrors C ``parsePackModeInfo`` (pack.c:1211).

    Parses the ``packmode`` attribute value.  Format::

        array[_<flags>][<size>]
        aspect[<float>]
        cluster
        graph
        node

    Returns a :class:`PackInfo` with ``mode``, ``flags``, ``sz``,
    and ``aspect`` populated.  ``margin`` and ``vals`` stay at
    defaults — the caller layers them in.
    """
    info = PackInfo(mode=default)
    if not spec:
        return info
    p = spec.strip()
    if p.startswith("array"):
        info.mode = PackMode.L_ARRAY
        rest = _chk_flags(p[len("array"):], info)
        try:
            sz = int(rest) if rest else 0
            if sz > 0:
                info.sz = sz
        except ValueError:
            pass
    elif p.startswith("aspect"):
        info.mode = PackMode.L_ASPECT
        try:
            info.aspect = float(p[len("aspect"):])
        except ValueError:
            info.aspect = 1.0
    elif p == "cluster":
        info.mode = PackMode.L_CLUST
    elif p == "graph":
        info.mode = PackMode.L_GRAPH
    elif p == "node":
        info.mode = PackMode.L_NODE
    return info


def get_pack_info(
    pack_attr: Optional[str],
    packmode_attr: Optional[str],
    default_mode: PackMode = PackMode.L_ARRAY,
    default_margin: int = DFLT_MARGIN,
) -> PackInfo:
    """Mirrors C ``getPackInfo`` (pack.c:1284).

    Combines the ``pack`` (margin) and ``packmode`` (mode + flags
    + size) attribute reads into a single :class:`PackInfo`.

    Parameters
    ----------
    pack_attr : str or None
        Value of the graph's ``pack`` attribute.  Integer →
        explicit margin; ``"true"`` (any case) → ``default_margin``;
        anything else → ``default_margin``.
    packmode_attr : str or None
        Value of the graph's ``packmode`` attribute.
    default_mode : PackMode
        Used when ``packmode_attr`` is None or unrecognized.
    default_margin : int
        Fallback margin in pt.
    """
    info = parse_pack_mode(packmode_attr, default_mode)
    info.margin = default_margin
    if pack_attr:
        try:
            v = int(pack_attr)
            if v >= 0:
                info.margin = v
        except ValueError:
            # "true" / "True" / "yes" → keep default_margin.
            pass
    return info


# ─────────────────────────────────────────────────────────────────
# array_rects — the actual array packing
# ─────────────────────────────────────────────────────────────────


@dataclass
class _AInfo:
    """Mirrors C ``ainfo`` (pack.c:550).  Per-rectangle scratch
    space used during the array sort + placement loops."""
    width: float
    height: float
    index: int


def _row_major_inc(c: int, r: int, nc: int, nr: int) -> tuple[int, int]:
    """Mirrors C ``INC(rowMajor=true, ...)`` — column-then-row
    iteration order (pack.c:588).
    """
    c += 1
    if c == nc:
        c = 0
        r += 1
    return c, r


def _col_major_inc(c: int, r: int, nc: int, nr: int) -> tuple[int, int]:
    """Mirrors C ``INC(rowMajor=false, ...)``  — row-then-column
    iteration order (pack.c:588).
    """
    r += 1
    if r == nr:
        r = 0
        c += 1
    return c, r


def array_rects(
    bbs: list[tuple[float, float, float, float]],
    info: PackInfo,
) -> list[tuple[float, float]]:
    """Mirrors C ``arrayRects`` (pack.c:604).

    Pack rectangles into a roughly-square grid.  Each input
    rectangle is given as ``(LL_x, LL_y, UR_x, UR_y)``; the
    output list contains the *displacement* ``(dx, dy)`` to apply
    to each rectangle's corners — i.e., the new lower-left of
    rect ``i`` is ``(LL_x + dx, LL_y + dy)``.

    The sort + per-cell placement matches C verbatim including
    the row-reversal trick (heights[0] holds the top row's
    cumulative offset, so row 0 ends up at the top of the
    output).

    Parameters
    ----------
    bbs : list of (LL_x, LL_y, UR_x, UR_y) tuples
        Bounding boxes of the rectangles to pack.
    info : PackInfo
        Configures grid size, sort order, and alignment flags.

    Returns
    -------
    list of (dx, dy)
        Per-rectangle displacement.  Same length as ``bbs``.
    """
    ng = len(bbs)
    if ng == 0:
        return []

    # 1. Grid sizing.
    sz = info.sz
    if info.flags & PK_COL_MAJOR:
        row_major = False
        if sz > 0:
            nr = sz
            nc = (ng + nr - 1) // nr
        else:
            nr = math.ceil(math.sqrt(ng))
            nc = (ng + nr - 1) // nr
    else:
        row_major = True
        if sz > 0:
            nc = sz
            nr = (ng + nc - 1) // nc
        else:
            nc = math.ceil(math.sqrt(ng))
            nr = (ng + nc - 1) // nc

    # 2. Per-rectangle scratch (width and height include margin).
    a_info: list[_AInfo] = []
    for i, (llx, lly, urx, ury) in enumerate(bbs):
        a_info.append(_AInfo(
            width=(urx - llx) + info.margin,
            height=(ury - lly) + info.margin,
            index=i,
        ))

    # 3. Sort.  ``sinfo`` is a list of references into ``a_info``
    # (matches C's ``ainfo **sinfo``).  We reorder ``sinfo``
    # without disturbing ``a_info[i].index`` so we can map back
    # to original positions.
    sinfo: list[_AInfo] = list(a_info)
    if info.vals is not None:
        # Sort ascending by user value (PK_USER_VALS).
        # ``info.vals[idx]`` keys into the original-index space.
        sinfo.sort(key=lambda ai: info.vals[ai.index])
    elif not (info.flags & PK_INPUT_ORDER):
        # Default: sort descending by width + height (acmpf,
        # pack.c:569) so the biggest rectangles get placed first.
        sinfo.sort(key=lambda ai: -(ai.width + ai.height))

    # 4. Compute per-column and per-row max sizes.
    widths = [0.0] * (nc + 1)
    heights = [0.0] * (nr + 1)
    c, r = 0, 0
    for ai in sinfo:
        widths[c] = max(widths[c], ai.width)
        heights[r] = max(heights[r], ai.height)
        if row_major:
            c, r = _row_major_inc(c, r, nc, nr)
        else:
            c, r = _col_major_inc(c, r, nc, nr)

    # 5. Convert column widths to cumulative x positions.
    # widths[i] becomes the left edge of column i.
    wd = 0.0
    for i in range(nc + 1):
        v = widths[i]
        widths[i] = wd
        wd += v

    # 6. Convert row heights to cumulative y positions in *reverse*
    # — heights[0] ends up holding the cumulative height of all
    # rows.  Row 0 becomes the top of the layout (y near max).
    ht = 0.0
    for i in range(nr, 0, -1):
        v = heights[i - 1]
        heights[i] = ht
        ht += v
    heights[0] = ht

    # 7. Place each rectangle inside its cell.
    places: list[tuple[float, float]] = [(0.0, 0.0)] * ng
    c, r = 0, 0
    for ai in sinfo:
        idx = ai.index
        llx, lly, urx, ury = bbs[idx]
        rect_w = urx - llx
        rect_h = ury - lly

        if info.flags & PK_LEFT_ALIGN:
            x = round(widths[c])
        elif info.flags & PK_RIGHT_ALIGN:
            x = round(widths[c + 1] - rect_w)
        else:
            x = round((widths[c] + widths[c + 1] - urx - llx) / 2.0)

        if info.flags & PK_TOP_ALIGN:
            y = round(heights[r] - rect_h)
        elif info.flags & PK_BOT_ALIGN:
            y = round(heights[r + 1])
        else:
            y = round((heights[r] + heights[r + 1] - ury - lly) / 2.0)

        places[idx] = (float(x), float(y))
        if row_major:
            c, r = _row_major_inc(c, r, nc, nr)
        else:
            c, r = _col_major_inc(c, r, nc, nr)

    return places


def put_rects(
    bbs: list[tuple[float, float, float, float]],
    info: PackInfo,
) -> Optional[list[tuple[float, float]]]:
    """Top-level dispatcher.  Mirrors C ``putRects`` (pack.c:930).

    Returns ``None`` for unsupported modes (``l_node`` /
    ``l_clust`` — C returns NULL too).  Osage's caller treats
    None by falling back to ``l_graph``, but in practice we
    always end up in ``l_array``.
    """
    if not bbs:
        return None
    if info.mode == PackMode.L_NODE or info.mode == PackMode.L_CLUST:
        return None
    if info.mode == PackMode.L_ARRAY:
        return array_rects(bbs, info)
    # Other modes (l_graph, l_aspect) aren't used by osage in
    # practice — fall back to array packing.
    return array_rects(bbs, info)
