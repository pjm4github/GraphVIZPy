"""C-aligned port of ``lib/circogen/block.c`` and
``lib/circogen/block.h``.

A :class:`Block` represents a biconnected component (maximal
2-connected subgraph) plus its layout state — node ordering on
the circle, radius, and child-block list.

The data model mirrors C ``block_t`` (block.h:26):

- ``child`` — node connecting this block to its parent (the
  shared articulation point in the parent block).
- ``next`` — sibling pointer in a parent's ``children``
  blocklist.
- ``sub_graph`` — the nodes/edges in this block.
- ``radius`` — radius of block + subtrees (after layout).
- ``rad0`` — original radius of just this block (before
  coalescing).
- ``circle_list`` — ordered list of nodes around the circle.
- ``children`` — child blocks (singly-linked list via
  ``first``/``last``).
- ``parent_pos`` — angle to place parent (only meaningful when
  block has 1 node).
- ``flags`` — currently only ``COALESCED_F``.

Because GraphvizPy uses Python objects rather than C pointers,
we model "next sibling" + "first/last" implicitly via Python
lists wherever possible — the C algorithms that explicitly walk
``b->next`` translate to ``for child in parent.children``.
The :class:`Blocklist` helper preserves C's append/insert
ordering semantics so the block-cut tree construction in
:mod:`gvpy.engines.layout.circo.blocktree` matches C behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ─────────────────────────────────────────────────────────────────
# Flags (block.h:54-56)
# ─────────────────────────────────────────────────────────────────

COALESCED_F: int = 1 << 0


@dataclass
class Block:
    """Mirrors C ``block_t`` (block.h:26).

    Notes:
    - ``sub_graph`` here is just the list of node names in the
      block; we don't replicate Graphviz's nested subgraph
      objects.
    - ``circle_list`` is a Python list of node names (C uses
      ``nodelist_t``, a list-of-Agnode_t).
    - ``children`` is a Python list of child Blocks (C uses
      ``blocklist_t`` with first/last pointers).  The
      :class:`Blocklist` helper exposes append-front /
      append-back operations that match C semantics.
    """
    # Node names in this block.
    sub_graph: list[str] = field(default_factory=list)
    # Node connecting this block to parent (shared articulation
    # point).  Mirrors C ``b->child`` — the node IN this block
    # whose DFS parent is the articulation point in the *parent*
    # block.
    child: Optional[str] = None
    # The articulation point in the PARENT block (=
    # ``PARENT(CHILD(b))`` in C / BLK_PARENT macro).  Cached
    # here for the engine's positioning code which looks it up
    # by name to find lnodes coords.  Set by
    # :func:`gvpy.engines.layout.circo.blocktree.create_blocktree`.
    parent_anchor: Optional[str] = None
    # Layout state.
    radius: float = 0.0
    rad0: float = 0.0
    circle_list: list[str] = field(default_factory=list)
    # Child blocks.  Order follows C ``appendBlock`` /
    # ``insertBlock`` semantics — see :class:`Blocklist`.
    children: list["Block"] = field(default_factory=list)
    # Angle to place parent (only meaningful for 1-node blocks).
    parent_pos: float = -1.0
    # Bitfield (currently only COALESCED_F).
    flags: int = 0
    # Per-node positions inside the block, relative to block
    # center.  Mirrors what C stores in ``ND_pos(n)`` for nodes
    # inside the block's sub_graph; we keep it on the Block to
    # avoid mutating the engine's lnodes during layout.
    node_pos: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Center after circPos positioning (absolute coords).
    center_x: float = 0.0
    center_y: float = 0.0
    # Cached PSI angle per node (used by circpos).  Mirrors C
    # ``PSI(neighbor)`` — the angle a neighbor will see its
    # parent block from after positioning.
    node_psi: dict[str, float] = field(default_factory=dict)
    # Edges in this block — kept for engine layout / crossings
    # algorithms that operate on edge lists.  Each entry is
    # ``(tail, head)``.  Not part of the C struct; an extra we
    # carry to avoid re-deriving from sub_graph + adjacency.
    edges: list[tuple[str, str]] = field(default_factory=list)
    # Engine back-reference to the parent block.  C uses
    # ``BLK_PARENT(b) = PARENT(CHILD(b))`` (a node lookup); we
    # cache the block pointer directly to avoid repeated lookups.
    parent: Optional["Block"] = None

    # ── Engine-compat aliases (legacy property names) ──
    # The pre-C-port circo engine used different field names;
    # these aliases let the engine code keep working without a
    # mass rename.

    @property
    def nodes(self) -> list[str]:
        """Alias for :attr:`sub_graph`."""
        return self.sub_graph

    @nodes.setter
    def nodes(self, value: list[str]) -> None:
        self.sub_graph = value

    @property
    def cut_node(self) -> str:
        """Alias for :attr:`parent_anchor` — the articulation
        point in the *parent* block.  Returns ``""`` (not None)
        for engine compatibility — old code checks ``if cut_node
        in lnodes`` and ``""`` is conveniently never a node name.
        """
        return self.parent_anchor or ""

    @cut_node.setter
    def cut_node(self, value: str) -> None:
        self.parent_anchor = value if value else None

    @property
    def circle_order(self) -> list[str]:
        """Alias for :attr:`circle_list`."""
        return self.circle_list

    @circle_order.setter
    def circle_order(self, value: list[str]) -> None:
        self.circle_list = value


def block_size(b: Block) -> int:
    """Mirrors C ``blockSize`` (block.c:41) — number of nodes."""
    return len(b.sub_graph)


def is_coalesced(b: Block) -> bool:
    """Mirrors C ``COALESCED`` macro (block.h:55)."""
    return bool(b.flags & COALESCED_F)


def set_coalesced(b: Block) -> None:
    """Mirrors C ``SET_COALESCED`` macro (block.h:56)."""
    b.flags |= COALESCED_F


# ─────────────────────────────────────────────────────────────────
# Blocklist — mirrors C blocklist_t with append/insert ordering
# ─────────────────────────────────────────────────────────────────


class Blocklist:
    """Helper wrapping a list of Blocks with C-style append/insert
    semantics.  Mirrors C ``blocklist_t`` (block.h:21).

    C's ``appendBlock`` adds to the end; ``insertBlock`` adds to
    the front.  These are used during block-cut tree
    construction to control the position of the root block.
    """

    def __init__(self):
        self.items: list[Block] = []

    def append(self, b: Block) -> None:
        """Mirrors C ``appendBlock`` (block.c:47)."""
        self.items.append(b)

    def insert(self, b: Block) -> None:
        """Mirrors C ``insertBlock`` (block.c:60)."""
        self.items.insert(0, b)

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __bool__(self):
        return bool(self.items)

    @property
    def first(self) -> Optional[Block]:
        return self.items[0] if self.items else None

    @property
    def last(self) -> Optional[Block]:
        return self.items[-1] if self.items else None


def make_block(node_names: Optional[list[str]] = None) -> Block:
    """Mirrors C ``mkBlock`` (block.c:25).  Creates an empty
    block with the given node names (or empty if none)."""
    return Block(sub_graph=list(node_names) if node_names else [])
