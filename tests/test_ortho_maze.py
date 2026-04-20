"""Structural tests for gvpy.engines.layout.ortho.maze (Phase 5 port).

No C harness: ``mkMaze`` requires a full ``graph_t`` scaffold
(libcgraph + libcommon + libgvc), which is disproportionate for this
module.  Instead we verify structural invariants against hand-computed
expectations on small fixtures:

- cell counts match the already-validated :func:`partition` output
- every cell has a 4-slot ``sides`` list
- every snode in the sgraph has both ``cells`` slots filled
  (:func:`_chk_sgraph` asserts this)
- per-cell edge count follows C's ``createSEdges`` formula (between 2
  and 6 depending on which sides are present)
- ``mark_small`` propagation into narrow-cell neighbours fires on
  explicitly-small gcells and leaves normal ones alone
- :func:`short_path` actually runs on the produced sgraph

Phase 6 integration exercises the maze end-to-end against real graphs
and catches any behavioural divergence from C that these invariants
miss.
"""

from __future__ import annotations

import pytest

from gvpy.engines.layout.common.geom import Ppoint
from gvpy.engines.layout.ortho import fpq
from gvpy.engines.layout.ortho.maze import (
    M_BOTTOM,
    M_LEFT,
    M_RIGHT,
    M_TOP,
    MZ_ISNODE,
    MZ_SMALLH,
    MZ_SMALLV,
    is_node,
    is_smallh,
    is_smallv,
    mk_maze,
)
from gvpy.engines.layout.ortho.partition import Boxf
from gvpy.engines.layout.ortho.sgraph import short_path


def _bb(llx: float, lly: float, urx: float, ury: float) -> Boxf:
    return Boxf(LL=Ppoint(llx, lly), UR=Ppoint(urx, ury))


# ---------- basic construction ----------


class TestMkMaze:
    def test_single_node(self):
        mp = mk_maze([_bb(40.0, 40.0, 60.0, 60.0)])
        assert mp.ngcells == 1
        # partition returns 8 cells around a single gcell in its bb.
        assert mp.ncells == 8
        assert len(mp.gcells) == 1
        assert len(mp.cells) == 8
        assert is_node(mp.gcells[0])

    def test_two_nodes(self):
        mp = mk_maze([
            _bb(20.0, 20.0, 40.0, 40.0),
            _bb(60.0, 60.0, 80.0, 80.0),
        ])
        assert mp.ngcells == 2
        # 5x5 grid around 2 gcells = 25 - 2 = 23 cells.
        assert mp.ncells == 23

    def test_empty_node_list_does_not_crash(self):
        mp = mk_maze([])
        assert mp.ngcells == 0
        # No nodes → partition on a tiny bb gives a single cell.
        assert mp.ncells == 1
        assert mp.sg is not None


# ---------- cell and sgraph structure ----------


class TestCellStructure:
    def test_every_cell_has_four_side_slots(self):
        mp = mk_maze([
            _bb(20.0, 20.0, 40.0, 40.0),
            _bb(60.0, 60.0, 80.0, 80.0),
        ])
        for cp in mp.cells:
            assert len(cp.sides) == 4
            assert cp.nsides == 4

    def test_corner_cell_has_only_inner_sides(self):
        """Corner cells of the partitioned BB should have their
        outer sides = None (no neighbour on the BB boundary)."""
        mp = mk_maze([_bb(40.0, 40.0, 60.0, 60.0)])
        # Sort cells by LL.x, LL.y to find the bottom-left corner cell.
        sorted_cells = sorted(mp.cells,
                              key=lambda c: (c.bb.LL.x, c.bb.LL.y))
        corner = sorted_cells[0]
        # Bottom-left corner: no LEFT side (on outer BB left edge) and
        # no BOTTOM side (on outer BB bottom edge).
        assert corner.sides[M_LEFT] is None
        assert corner.sides[M_BOTTOM] is None
        # Internal TOP/RIGHT sides exist.
        assert corner.sides[M_TOP] is not None
        assert corner.sides[M_RIGHT] is not None


class TestSgraphStructure:
    def test_all_snodes_have_both_cells_filled(self):
        mp = mk_maze([
            _bb(20.0, 20.0, 40.0, 40.0),
            _bb(60.0, 60.0, 80.0, 80.0),
        ])
        sg = mp.sg
        assert sg is not None
        for i in range(sg.nnodes):
            np = sg.nodes[i]
            assert np.cells[0] is not None, f"snode {i} cells[0]"
            assert np.cells[1] is not None, f"snode {i} cells[1]"

    def test_snode_isvert_flag(self):
        """vdict snodes (stored for left/right sides) are ``is_vert=True``;
        hdict snodes (top/bottom sides) are ``is_vert=False``."""
        mp = mk_maze([_bb(40.0, 40.0, 60.0, 60.0)])
        for cp in mp.cells:
            for slot in (M_LEFT, M_RIGHT):
                np = cp.sides[slot]
                if np is not None:
                    assert np.is_vert is True
            for slot in (M_TOP, M_BOTTOM):
                np = cp.sides[slot]
                if np is not None:
                    assert np.is_vert is False

    def test_sgraph_capacity(self):
        mp = mk_maze([_bb(40.0, 40.0, 60.0, 60.0)])
        # create_sgraph capacity = 4 * ncells + 2.
        assert len(mp.sg.nodes) == 4 * mp.ncells + 2
        assert mp.sg.nnodes <= 4 * mp.ncells


class TestEdgeCount:
    def test_edge_count_formula(self):
        """``createSEdges`` emits an edge per pair of present adjacent
        sides.  For a cell with all 4 sides, that's 6 edges; for
        corner cells missing 2 sides, it's fewer."""
        mp = mk_maze([
            _bb(20.0, 20.0, 40.0, 40.0),
            _bb(60.0, 60.0, 80.0, 80.0),
        ])
        for cp in mp.cells:
            present = [s is not None for s in cp.sides]
            expected = 0
            L, T, R, B = (
                present[M_LEFT], present[M_TOP],
                present[M_RIGHT], present[M_BOTTOM],
            )
            if L and T: expected += 1
            if T and R: expected += 1
            if L and B: expected += 1
            if B and R: expected += 1
            if T and B: expected += 1
            if L and R: expected += 1
            assert cp.nedges == expected, (
                f"cell bb={cp.bb}: "
                f"present={present}, nedges={cp.nedges}, expected={expected}"
            )


# ---------- markSmall ----------


class TestMarkSmall:
    def test_normal_gcell_no_small_flags(self):
        """A gcell with ``height > 7`` has ``chansz >= 2``, i.e. not
        IS_SMALL — no SMALLV/SMALLH propagation."""
        mp = mk_maze([_bb(20.0, 20.0, 40.0, 40.0)])  # 20x20 gcell
        for cp in mp.cells:
            assert not is_smallv(cp)
            assert not is_smallh(cp)

    def test_narrow_gcell_propagates_smallv(self):
        """A gcell narrower than 7 units triggers IS_SMALL on its
        vertical dimension, propagating SMALLV to left/right neighbour
        cells — but ``IS_SMALL`` checks ``(dim - 3) / 2 < 2``, i.e.
        ``dim < 7``, so we need a short (y-dim small) gcell."""
        # A short gcell: height = 6 → chansz = 1.5 < 2 → IS_SMALL.
        mp = mk_maze([_bb(20.0, 27.0, 80.0, 33.0)])
        # At least one cell should now carry MZ_SMALLV from markSmall.
        any_smallv = any(is_smallv(c) for c in mp.cells)
        assert any_smallv, (
            "expected at least one cell to inherit MZ_SMALLV "
            "from the narrow gcell"
        )


# ---------- integration: short_path on the produced sgraph ----------


class TestSgraphUsable:
    def test_short_path_runs_between_opposite_snodes(self):
        """End-to-end: a 2-node maze's sgraph should be connected
        enough to run a shortest-path query between any two snodes
        of opposite orientation."""
        mp = mk_maze([
            _bb(20.0, 20.0, 40.0, 40.0),
            _bb(60.0, 60.0, 80.0, 80.0),
        ])
        sg = mp.sg
        # Pick the first is_vert and first non-is_vert snode.
        v_node = next(sg.nodes[i] for i in range(sg.nnodes)
                      if sg.nodes[i].is_vert)
        h_node = next(sg.nodes[i] for i in range(sg.nnodes)
                      if not sg.nodes[i].is_vert)
        pq = fpq.pq_gen(sg.nnodes)
        rc = short_path(pq, sg, v_node, h_node)
        assert rc == 0
        # Path exists (the maze is fully connected).
        from gvpy.engines.layout.ortho.sgraph import UNSEEN
        assert h_node.n_val != UNSEEN


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
