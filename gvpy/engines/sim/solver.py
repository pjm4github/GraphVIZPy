"""CBD solver — three-phase Mealy semantics for synchronous block diagrams.

Implements the simulation step described in:

    Van Tendeloo, Y. and Vangheluwe, H.  *PythonPDEVS: a distributed
    Parallel DEVS simulator.*  Spring Simulation Multi-Conference,
    2014. — and the PyCBD companion that introduces the three-phase
    Mealy semantics for Causal Block Diagrams.

The solver runs each iteration as three sequential phases:

    Phase 1 — OUTPUT
        Walk every block in topological order.  Each block's
        :meth:`Block.compute` reads its (already-updated) inputs
        and writes its outputs.  Algebraic blocks downstream
        therefore see fresh outputs from their upstream
        algebraic blocks; delay blocks see only their own
        ``state`` (which holds the *previous* iteration's input).

    Phase 2 — UPDATE
        Walk every :class:`gvpy.engines.sim.cbd.StatefulBlock` and
        run :meth:`StatefulBlock.update_state`, which uses the
        inputs that were just consumed by phase 1 to compute the
        next iteration's state.  This is the *Mealy* part: state
        transition uses current inputs, not next inputs.

    Phase 3 — ADVANCE
        Tick the clock; ``current_iter += 1``.

The split is what makes algebraic loops tractable: any cycle in
the dependency graph must contain at least one
:class:`gvpy.engines.sim.cbd.DelayBlock`, and we can topologically
sort the *non-delay* edges (treating delay outputs as graph
sources) to obtain a valid evaluation order.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from .clock import DiscreteClock

if TYPE_CHECKING:
    from .cbd import Block, CompoundBlock


def topological_sort(blocks: list["Block"]) -> list["Block"]:
    """Topologically sort ``blocks`` so each block follows its inputs.

    DelayBlocks are treated as graph **sources** (their outputs do
    not depend on current-iteration inputs), which is what cuts
    algebraic loops.  Non-delay blocks must form a DAG once delay
    edges are removed; if any cycle remains, raises ``ValueError``.

    Algorithm: Kahn's algorithm with in-degree counts.  In-degree
    for a non-delay block is the count of upstream non-delay
    suppliers; delay blocks always start with in-degree 0.
    """
    # Lazy import — solver and cbd otherwise reference each other
    # at module import time.
    from .cbd import DelayBlock

    # Build the dependency graph: block -> set of blocks that feed
    # one of its inputs (delay sources are excluded).
    deps: dict["Block", set["Block"]] = {b: set() for b in blocks}
    dependents: dict["Block", set["Block"]] = {b: set() for b in blocks}

    block_set = set(blocks)
    for blk in blocks:
        if isinstance(blk, DelayBlock):
            # Delays are sources — their outputs depend only on
            # past state, not current inputs.
            continue
        for port in blk.input_ports.values():
            src_port = port.connected_from
            if src_port is None:
                continue
            src_blk = src_port.owner
            if src_blk not in block_set:
                continue  # external port — ignore
            if isinstance(src_blk, DelayBlock):
                continue  # delay edge — doesn't constrain order
            deps[blk].add(src_blk)
            dependents[src_blk].add(blk)

    # Kahn's algorithm
    in_degree = {b: len(deps[b]) for b in blocks}
    ready = [b for b in blocks if in_degree[b] == 0]
    schedule: list["Block"] = []

    while ready:
        # Stable order: keep input list order among ready nodes.
        blk = ready.pop(0)
        schedule.append(blk)
        for downstream in dependents[blk]:
            in_degree[downstream] -= 1
            if in_degree[downstream] == 0:
                ready.append(downstream)

    if len(schedule) != len(blocks):
        unresolved = [b.name for b in blocks
                      if b not in schedule]
        raise ValueError(
            f"Algebraic loop detected — no DelayBlock breaks the "
            f"cycle.  Unresolved blocks: {unresolved}"
        )
    return schedule


class CBDSolver:
    """Three-phase Mealy step driver for a :class:`CompoundBlock`.

    Holds the topologically-sorted schedule of leaf blocks and the
    discrete clock.  ``init`` builds the schedule; ``step`` runs
    one Mealy step (output → update → advance).
    """

    def __init__(self, root: "CompoundBlock",
                 clock: Optional[DiscreteClock] = None):
        self.root = root
        self.clock = clock if clock is not None else DiscreteClock()
        self.schedule: list["Block"] = []

    def init(self) -> None:
        """Flatten the compound and topologically sort the leaves."""
        flat = self.root.flatten()
        self.schedule = topological_sort(flat)

    @property
    def current_iter(self) -> int:
        return self.clock.iteration

    def step(self) -> None:
        """Run one three-phase Mealy step.

        See module docstring for the phase semantics.
        """
        # Lazy import for the StatefulBlock isinstance check.
        from .cbd import StatefulBlock

        cur = self.current_iter

        # ── Phase 1 — OUTPUT ─────────────────────────────────
        for blk in self.schedule:
            blk.compute(cur)

        # ── Phase 2 — UPDATE ─────────────────────────────────
        for blk in self.schedule:
            if isinstance(blk, StatefulBlock):
                blk.update_state(cur)

        # ── Phase 3 — ADVANCE ────────────────────────────────
        self.clock.advance(self.clock.delta_t)

    def run(self, num_iters: int) -> None:
        """Run ``num_iters`` Mealy steps."""
        for _ in range(num_iters):
            self.step()
