"""C-aligned port of ``lib/circogen/nodelist.c`` operations.

Tiny helper module — all operations work on plain Python lists
of node names (we don't need the full C list-of-Agnode_t type).
"""
from __future__ import annotations


def append_at(lst: list, position: int, item) -> None:
    """Mirrors C ``appendNodelist`` (nodelist.c:21).

    Insert ``item`` at index ``position``, shifting everything
    after it to the right.
    """
    assert 0 <= position <= len(lst)
    lst.insert(position, item)


def realign(lst: list, np: int) -> None:
    """Mirrors C ``realignNodelist`` (nodelist.c:38).

    Rotate the list so that index ``np`` becomes the new front.
    """
    assert 0 <= np < len(lst)
    if np == 0:
        return
    # Equivalent to popping head np times and pushing to back —
    # but we do it as a slice for clarity.
    lst[:] = lst[np:] + lst[:np]


def insert_relative(
    lst: list, item, neighbor, position: int,
) -> None:
    """Mirrors C ``insertNodelist`` (nodelist.c:47).

    Remove ``item`` from ``lst``, then re-insert it adjacent to
    ``neighbor``: before if ``position == 0``, after otherwise.
    """
    if item in lst:
        lst.remove(item)
    for i, here in enumerate(lst):
        if here == neighbor:
            if position == 0:
                append_at(lst, i, item)
            else:
                append_at(lst, i + 1, item)
            return


def reverse_append(l1: list, l2: list) -> None:
    """Mirrors C ``reverseAppend`` (nodelist.c:74).

    Reverse ``l2`` in place, then append it onto ``l1``.  ``l2``
    is left empty.
    """
    l2.reverse()
    l1.extend(l2)
    l2.clear()
