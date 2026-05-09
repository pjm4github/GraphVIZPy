"""C-aligned port of ``lib/circogen/circpos.c`` —
recursive child-block positioning around the parent block.

After every block has had its own circular layout computed by
:mod:`gvpy.engines.layout.circo.blockpath`, this module walks
the block-cut tree top-down to place each child block:

1. ``do_block`` (mirrors C ``doBlock``) — depth-first recursion
   that lays out each child block first, then calls
   :func:`position` to place children around the parent's
   articulation points.
2. ``position`` (mirrors C ``position``) — for each
   articulation point ("ISPARENT" node) in the parent block,
   call :func:`get_info` to compute the child fan's geometry,
   then :func:`set_info` (when there are 2+ articulation
   points) to scale child fans so they don't overlap each
   other along the parent circle, then
   :func:`position_children` to actually place each child.
3. ``position_children`` (mirrors C ``positionChildren``) —
   distribute children at one articulation point around an
   arc, respecting their individual radii.  Calls
   :func:`get_rotation` + :func:`apply_delta` to translate
   each child to its final position.
4. ``get_rotation`` (mirrors C ``getRotation``) — closed-form
   rotation math that aligns each child block with its parent.
   Handles 1-node, 2-node, and N-node blocks separately, plus
   the "coalesced" case (block with a single child block where
   the parent block's coords got shifted).
5. ``apply_delta`` (mirrors C ``applyDelta``) — apply the
   rotation + translation to a block and recurse to its
   subtree.

Coordinates are stored on each :class:`Block` as
``node_pos[name] = (x, y)`` (relative to the block's own
``(center_x, center_y)``).  After ``circ_pos`` returns, each
node's absolute position is at ``block.center + block.node_pos[n]``.
The engine wiring layer extracts these and writes them into
``self.lnodes``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from gvpy.engines.layout.circo.block import (
    Block,
    is_coalesced,
    set_coalesced,
)


# ─────────────────────────────────────────────────────────────────
# State shared during one circ_pos invocation
# ─────────────────────────────────────────────────────────────────


@dataclass
class _PosInfo:
    """Mirrors C ``posinfo_t`` (circpos.c:167).

    One per articulation point in a parent block.
    """
    n: str = ""
    theta: float = 0.0       # angle of n on the parent circle
    min_radius: float = 0.0  # parent_radius + min_dist + max_child_radius
    max_radius: float = 0.0  # max child radius at this articulation point
    diameter: float = 0.0    # sum of child diameters at this articulation point
    scale: float = 1.0       # scale factor to enlarge min_radius for non-overlap
    child_count: int = 0


@dataclass
class _PosState:
    """Mirrors C ``posstate`` (circpos.c:157).

    One per parent block during ``position``.
    """
    radius: float = 0.0          # parent block radius
    subtree_r: float = 0.0       # max subtree radius after this layer
    node_angle: float = 0.0      # angle each node spans on parent circle
    first_angle: float = -1.0    # smallest child angle (1-node parent)
    last_angle: float = -1.0     # largest child angle (1-node parent)
    children: list[Block] = field(default_factory=list)
    neighbor: Optional[str] = None  # CHILD(sn) — node-in-parent linking up


# ─────────────────────────────────────────────────────────────────
# get_rotation
# ─────────────────────────────────────────────────────────────────


def get_rotation(
    sn: Block,
    x: float,
    y: float,
    theta: float,
) -> float:
    """Mirrors C ``getRotation`` (circpos.c:50).

    Determine how much to rotate child block ``sn`` for best
    visual placement next to its parent, given that ``sn``'s
    center is at ``(x, y)`` relative to the parent and angle
    ``theta = atan2(y, x)``.

    Returns the angle (radians) to rotate ``sn``.

    Three branches:

    - **1-node block**: ``parent_pos`` was already set by the
      child's own ``layout_block``; just rotate to align it.
    - **2-node block**: rotate the line of the two nodes
      perpendicular to ``theta``.
    - **N-node block**: find the node in ``sn`` closest to the
      parent (in absolute coords) and rotate so it ends up
      adjacent to the parent.  For coalesced blocks, the origin
      of ``sn`` isn't at its center, so we use a different
      closed-form.
    """
    # Branch 1: 1-node block (or any block whose own
    # layout_block already set parent_pos to a valid angle).
    if sn.parent_pos >= 0:
        theta += math.pi - sn.parent_pos
        if theta < 0:
            theta += 2.0 * math.pi
        return theta

    # Branch 2: 2-node block.
    count = len(sn.circle_list)
    if count == 2:
        return theta - math.pi / 2.0

    # Branch 3: N-node block.  Find node in sn connected to the
    # parent block (== sn.child) — that's the "neighbor".
    neighbor = sn.child
    if neighbor is None or neighbor not in sn.node_pos:
        return 0.0

    nx, ny = sn.node_pos[neighbor]
    new_x = nx + x
    new_y = ny + y
    mindist2 = math.hypot(new_x, new_y)
    closest_node = neighbor

    for n_iter in sn.sub_graph:
        if n_iter == neighbor or n_iter not in sn.node_pos:
            continue
        ix, iy = sn.node_pos[n_iter]
        d = math.hypot(ix + x, iy + y)
        if d < mindist2:
            mindist2 = d
            closest_node = n_iter

    if neighbor != closest_node:
        rho = sn.rad0
        r = sn.radius - rho
        n_x = sn.node_pos[neighbor][0]
        if is_coalesced(sn) and -r < n_x:
            # Coalesced branch (circpos.c:97-103):
            R = math.hypot(x, y)
            n_y = sn.node_pos[neighbor][1]
            phi = math.atan2(n_y, n_x + r)
            ll = r - rho / math.cos(phi) if math.cos(phi) != 0 else r
            if R != 0:
                arg = ll / R * math.cos(phi)
                arg = max(-1.0, min(1.0, arg))
                theta += math.pi / 2.0 - phi - math.asin(arg)
            else:
                theta = 0.0
        else:
            # Normal branch (circpos.c:104-109):
            phi = math.atan2(
                sn.node_pos[neighbor][1],
                sn.node_pos[neighbor][0],
            )
            theta += math.pi - phi - sn.node_psi.get(neighbor, 0.0)
            if theta > 2.0 * math.pi:
                theta -= 2.0 * math.pi
    else:
        theta = 0.0

    return theta


# ─────────────────────────────────────────────────────────────────
# apply_delta
# ─────────────────────────────────────────────────────────────────


def apply_delta(
    sn: Block,
    x: float,
    y: float,
    rotate: float,
) -> None:
    """Mirrors C ``applyDelta`` (circpos.c:118).

    Recursively rotate each node's coords by ``rotate`` (around
    the block's local origin) and translate by ``(x, y)``.

    The C version mutates ``ND_pos(n)`` in place because nodes
    are owned by the global graph; we mutate ``sn.node_pos`` and
    propagate to children.
    """
    cos_r = math.cos(rotate)
    sin_r = math.sin(rotate)
    for n in list(sn.node_pos.keys()):
        ox, oy = sn.node_pos[n]
        X = ox * cos_r - oy * sin_r
        Y = ox * sin_r + oy * cos_r
        sn.node_pos[n] = (X + x, Y + y)
    for child in sn.children:
        apply_delta(child, x, y, rotate)


# ─────────────────────────────────────────────────────────────────
# get_info / set_info / position_children / position
# ─────────────────────────────────────────────────────────────────


def _get_info(
    pi: _PosInfo,
    stp: _PosState,
    min_dist: float,
) -> float:
    """Mirrors C ``getInfo`` (circpos.c:179).

    For each child whose ``parent_anchor == pi.n``, accumulate:
    - ``child_count``
    - ``max_radius`` = max child radius
    - ``diameter`` = Σ (2·radius + min_dist)

    Returns ``max_radius``.
    """
    max_radius = 0.0
    diameter = 0.0
    child_count = 0
    for child in stp.children:
        if child.parent_anchor == pi.n:
            child_count += 1
            max_radius = max(max_radius, child.radius)
            diameter += 2.0 * child.radius + min_dist
    pi.diameter = diameter
    pi.child_count = child_count
    pi.min_radius = stp.radius + min_dist + max_radius
    pi.max_radius = max_radius
    return max_radius


def _set_info(
    p0: _PosInfo,
    p1: _PosInfo,
    delta: float,
) -> None:
    """Mirrors C ``setInfo`` (circpos.c:202).

    Adjust the ``scale`` factors of two adjacent articulation
    points so their child fans don't overlap along the parent
    circle.  ``delta`` is the angular distance between p0 and
    p1.
    """
    if delta == 0.0 or p0.min_radius == 0 or p1.min_radius == 0:
        return
    t = (
        p0.diameter * p1.min_radius + p1.diameter * p0.min_radius
    ) / (2.0 * delta * p0.min_radius * p1.min_radius)
    t = max(t, 1.0)
    p0.scale = max(p0.scale, t)
    p1.scale = max(p1.scale, t)


def _position_children(
    info: _PosInfo,
    stp: _PosState,
    length: int,
    min_dist: float,
) -> None:
    """Mirrors C ``positionChildren`` (circpos.c:214).

    Distribute children at this articulation point around an
    arc.  Each child's center sits on a circle of radius
    ``info.scale * info.min_radius`` (or larger for 1-node
    parents that need extra room).  The ``mindist_angle`` term
    leaves a small gap between adjacent children.
    """
    sn_radius = stp.subtree_r
    first_angle = stp.first_angle
    last_angle = stp.last_angle

    child_radius = info.scale * info.min_radius
    if length == 1:
        # Special case for 1-node parent block (circpos.c:226-232).
        child_angle = 0.0
        d = info.diameter / (2.0 * math.pi)
        child_radius = max(child_radius, d)
        d2 = 2.0 * math.pi * child_radius - info.diameter
        if d2 > 0 and info.child_count > 0:
            min_dist = min_dist + d2 / info.child_count
    else:
        child_angle = info.theta - info.diameter / (2.0 * child_radius)

    sn_radius = max(sn_radius, child_radius + info.max_radius)

    mindist_angle = min_dist / child_radius if child_radius > 0 else 0.0

    mid_child = (info.child_count + 1) // 2
    mid_angle = 0.0
    cnt = 0
    for child in stp.children:
        if child.parent_anchor != info.n:
            continue
        if not child.circle_list:
            continue

        incident_angle = (
            child.radius / child_radius if child_radius > 0 else 0.0
        )
        if length == 1:
            if child_angle != 0.0:
                if info.child_count == 2:
                    child_angle = math.pi
                else:
                    child_angle += incident_angle
            if first_angle < 0:
                first_angle = child_angle
            last_angle = child_angle
        else:
            if info.child_count == 1:
                child_angle = info.theta
            else:
                child_angle += incident_angle + mindist_angle / 2.0

        delta_x = child_radius * math.cos(child_angle)
        delta_y = child_radius * math.sin(child_angle)

        rotate_angle = get_rotation(child, delta_x, delta_y, child_angle)
        apply_delta(child, delta_x, delta_y, rotate_angle)

        if length == 1:
            child_angle += incident_angle + mindist_angle
        else:
            child_angle += incident_angle + mindist_angle / 2.0
        cnt += 1
        if cnt == mid_child:
            mid_angle = child_angle

    if length > 1 and info.n == stp.neighbor:
        # Cache the mid-angle PSI for the parent block's
        # articulation node so its own parent's getRotation can
        # use it.  Mirrors C ``PSI(info->n) = midAngle``.
        for ancestor_n in (info.n,):
            # We don't have direct access to the parent block
            # here; the engine layer will have written the
            # parent's node_psi by the time we get here for the
            # grandparent.  Stash on the child block itself.
            pass
        # Plus: the parent block of THIS sn (call it pp).  The
        # caller ``position`` knows which block this is and
        # writes node_psi onto it via the return value.
        # We store it via a side-effect on stp:
        stp._mid_psi_n = info.n  # type: ignore[attr-defined]
        stp._mid_psi = mid_angle  # type: ignore[attr-defined]

    stp.subtree_r = sn_radius
    stp.first_angle = first_angle
    stp.last_angle = last_angle


def position(
    parent_block: Block,
    state_nodes_is_parent: dict[str, bool],
    nodepath: list[str],
    min_dist: float,
) -> float:
    """Mirrors C ``position`` (circpos.c:307).

    Position all children of ``parent_block`` around the
    articulation points in ``nodepath`` (which is
    ``parent_block.circle_list``).

    ``state_nodes_is_parent[n] == True`` for nodes that are
    articulation points (= linked to one or more child blocks).
    Mirrors C ``ISPARENT(n)`` flag.

    Returns the "center angle" used by the caller to set
    ``parent_block.parent_pos`` if this block has only one node.
    """
    state = _PosState(
        children=list(parent_block.children),
        radius=parent_block.radius,
        subtree_r=parent_block.radius,
        neighbor=parent_block.child,
        node_angle=2.0 * math.pi / max(len(nodepath), 1),
        first_angle=-1.0,
        last_angle=-1.0,
    )

    parents: list[_PosInfo] = []
    counter = 0
    max_radius = 0.0

    for n in nodepath:
        theta = counter * state.node_angle
        counter += 1
        if state_nodes_is_parent.get(n, False):
            pi = _PosInfo(n=n, theta=theta)
            r = _get_info(pi, state, min_dist)
            max_radius = max(max_radius, r)
            parents.append(pi)

    num_parents = len(parents)
    if num_parents == 1:
        parents[0].scale = 1.0
    elif num_parents == 2:
        delta = parents[1].theta - parents[0].theta
        if delta > math.pi:
            delta = 2.0 * math.pi - delta
        _set_info(parents[0], parents[1], delta)
    elif num_parents > 2:
        for i in range(num_parents):
            curr = parents[i]
            if i + 1 == num_parents:
                next_p = parents[0]
                delta = next_p.theta - curr.theta + 2.0 * math.pi
            else:
                next_p = parents[i + 1]
                delta = next_p.theta - curr.theta
            _set_info(curr, next_p, delta)

    for pi in parents:
        _position_children(pi, state, len(nodepath), min_dist)
        # Propagate any cached mid-PSI for this articulation
        # point onto parent_block's node_psi map so the
        # grandparent's getRotation can read it.
        mid_n = getattr(state, "_mid_psi_n", None)
        if mid_n is not None:
            parent_block.node_psi[mid_n] = getattr(state, "_mid_psi", 0.0)

    # Coalescing: when the parent block has exactly one *total*
    # child block (across all articulation points), C
    # collapses the parent into that child to save space:
    # shift the parent's interior over by half the child fan's
    # extent, expand the parent's radius to encompass it, and
    # mark the block COALESCED.  Mirrors C circpos.c:380-385.
    # ``child_count`` here is the total number of children
    # passed to C's ``position`` (== ``sn->n_children``).
    total_child_count = len(parent_block.children)
    if total_child_count == 1:
        apply_delta(
            parent_block,
            -(max_radius + min_dist / 2.0),
            0.0,
            0.0,
        )
        parent_block.radius += min_dist / 2.0 + max_radius
        set_coalesced(parent_block)
    else:
        parent_block.radius = state.subtree_r

    angle = (state.first_angle + state.last_angle) / 2.0 - math.pi
    return angle


# ─────────────────────────────────────────────────────────────────
# do_block + circ_pos (top-level entry)
# ─────────────────────────────────────────────────────────────────


def do_block(
    sn: Block,
    block_adjacency: dict[str, list[str]],
    widths: dict[str, float],
    heights: dict[str, float],
    min_dist: float,
) -> None:
    """Mirrors C ``doBlock`` (circpos.c:395).

    Recursive entry: lay out child blocks first, then this
    block, then attach children.  After return, every node in
    the subtree has its final position in ``block.node_pos``
    (relative to the subtree's own origin).
    """
    from gvpy.engines.layout.circo.blockpath import layout_block

    # 1. Recurse into child blocks first.
    child_count = 0
    for child in sn.children:
        do_block(child, block_adjacency, widths, heights, min_dist)
        child_count += 1

    # 2. Lay out THIS block in its own (0, 0)-anchored frame.
    longest_path = layout_block(
        sn, block_adjacency, widths, heights, min_dist,
    )
    length = len(longest_path)

    # 3. Attach children.
    center_angle = math.pi
    if child_count > 0:
        # Build is_parent map from this block's children.
        is_parent_map: dict[str, bool] = {}
        for ch in sn.children:
            if ch.parent_anchor:
                is_parent_map[ch.parent_anchor] = True
        center_angle = position(sn, is_parent_map, longest_path, min_dist)

    if length == 1 and sn.parent_anchor is not None:
        # This is a single-node child block; record the angle
        # at which its parent should be drawn relative to it.
        sn.parent_pos = center_angle
        if sn.parent_pos < 0:
            sn.parent_pos += 2.0 * math.pi


def circ_pos(
    root: Block,
    block_adjacency: dict[str, list[str]],
    widths: dict[str, float],
    heights: dict[str, float],
    min_dist: float,
) -> None:
    """Mirrors C ``circPos`` (circpos.c:423).

    Top-level entry: call :func:`do_block` on the root, then
    leave the engine to read ``root.node_pos`` for absolute
    coords.
    """
    do_block(root, block_adjacency, widths, heights, min_dist)
