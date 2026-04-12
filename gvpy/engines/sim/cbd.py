"""Causal Block Diagram primitives (PyCBD-inspired).

Implements the block / port / connection model from PyCBD as
described in:

    Van Tendeloo, Y. and Vangheluwe, H.  *An evaluation of DEVS
    simulation tools.*  Simulation, 2018.  (And the companion
    PyCBD paper that introduces the three-phase Mealy semantics
    used by :mod:`gvpy.engines.sim.solver`.)

Class hierarchy
---------------
::

    Block                       — atomic, stateless primitive
    └── StatefulBlock           — has internal state, updated in phase 2
        └── DelayBlock          — z^-1: cuts algebraic loops
    CompoundBlock(Block)        — hierarchical container of sub-blocks
                                  + connections; itself a Block so it
                                  can nest

Atomic primitives provided
--------------------------
- :class:`ConstantBlock`  — emits a fixed value on its single output
- :class:`GainBlock`      — multiplies its input by a constant ``k``
- :class:`AdderBlock`     — sums an arbitrary number of inputs
- :class:`NegatorBlock`   — outputs the negation of its single input
- :class:`ProductBlock`   — multiplies an arbitrary number of inputs
- :class:`DelayBlock`     — z^-1 (output(t) = state; state(t+1) = input)

These mirror the PyCBD primitive library.  Higher-level blocks
(integrator, sine source, derivator, ...) can be added later as
StatefulBlock subclasses.

Three-phase Mealy step
----------------------
The :class:`gvpy.engines.sim.solver.CBDSolver` orchestrates each step:

1. **Output phase**: walk blocks in topological order; each block's
   :meth:`Block.compute` reads its inputs (which were already
   updated by upstream blocks earlier in the same step, or by the
   previous step's state for delay blocks) and writes its outputs.

2. **Update phase**: every :class:`StatefulBlock` runs
   :meth:`StatefulBlock.update_state` to swap in its next state
   based on the inputs that were just consumed.  This is the
   *Mealy* part — the state transition uses the inputs of *this*
   step.

3. **Advance phase**: the clock ticks; ``current_iter += 1``.

This separation is what makes algebraic loops solvable: any cycle
in the connection graph must contain at least one
:class:`DelayBlock` (whose output depends only on past state, not
current input), so the topological sort succeeds with delays acting
as cycle-breakers.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable, Optional

from .base import SimulationView
from .clock import DiscreteClock

if TYPE_CHECKING:
    from gvpy.core.graph import Graph


# ── Ports and connections ───────────────────────────────────────────


class Port:
    """A named input or output slot on a :class:`Block`.

    Holds the most recently written value (output ports) or the
    most recently read upstream value (input ports).  Connections
    are stored on the input port (``connected_from``) so the
    fan-in is single-source by construction.
    """

    def __init__(self, name: str, owner: "Block", is_output: bool):
        self.name = name
        self.owner = owner
        self.is_output = is_output
        self.value: Any = None
        # For input ports: which output port feeds us (None if floating)
        self.connected_from: Optional["Port"] = None

    def __repr__(self) -> str:
        kind = "out" if self.is_output else "in"
        return f"<Port {self.owner.name}.{self.name}[{kind}]={self.value!r}>"


class Connection:
    """An explicit (src_port -> dst_port) link.

    Stored on the parent :class:`CompoundBlock` so it can be
    enumerated for the topological sort and for serialization.  The
    actual data flow happens through ``Port.connected_from`` (the
    input port pulls from its source on every read).
    """

    def __init__(self, src: Port, dst: Port):
        if not src.is_output:
            raise ValueError(f"src must be an output port: {src}")
        if dst.is_output:
            raise ValueError(f"dst must be an input port: {dst}")
        self.src = src
        self.dst = dst
        dst.connected_from = src

    def __repr__(self) -> str:
        return (f"<Connection {self.src.owner.name}.{self.src.name} -> "
                f"{self.dst.owner.name}.{self.dst.name}>")


# ── Block hierarchy ─────────────────────────────────────────────────


class Block:
    """Atomic CBD block.

    Concrete subclasses override :meth:`compute` to write their
    outputs based on their (already-updated) inputs.  Stateless by
    default — see :class:`StatefulBlock` for blocks that carry
    iteration-to-iteration state.
    """

    def __init__(self, name: str,
                 input_names: Iterable[str] = (),
                 output_names: Iterable[str] = ("OUT",)):
        self.name = name
        self.parent: Optional["CompoundBlock"] = None
        self.input_ports: dict[str, Port] = {
            n: Port(n, self, is_output=False) for n in input_names
        }
        self.output_ports: dict[str, Port] = {
            n: Port(n, self, is_output=True) for n in output_names
        }

    # Port access -------------------------------------------------

    def get_input_value(self, name: str = "IN") -> Any:
        """Return the current value of input port ``name`` (pulling
        from its upstream source if connected)."""
        port = self.input_ports[name]
        if port.connected_from is not None:
            port.value = port.connected_from.value
        return port.value

    def set_output_value(self, name: str, value: Any) -> None:
        """Write ``value`` to output port ``name``."""
        self.output_ports[name].value = value

    def get_output_value(self, name: str = "OUT") -> Any:
        """Return the current value of output port ``name``."""
        return self.output_ports[name].value

    # Compute -----------------------------------------------------

    def compute(self, current_iter: int) -> None:
        """Update output ports for the current iteration.

        Stateless default: read inputs, write nothing.  Override
        in subclasses.
        """

    # Convenience -------------------------------------------------

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}>"


class StatefulBlock(Block):
    """A block with internal state updated in the Mealy step's phase 2.

    Subclasses override :meth:`update_state` to compute the next
    state based on the inputs of the current iteration.  The
    :meth:`compute` method writes outputs based on the *current*
    state (so an observer at any iteration sees a consistent
    snapshot before the state transition).
    """

    def __init__(self, name: str,
                 input_names: Iterable[str] = ("IN",),
                 output_names: Iterable[str] = ("OUT",),
                 initial_state: Any = 0.0):
        super().__init__(name, input_names, output_names)
        self.state: Any = initial_state
        self._initial_state: Any = initial_state

    def update_state(self, current_iter: int) -> None:
        """Compute the next state from current inputs and state.

        Default no-op; override in subclasses.
        """

    def reset(self) -> None:
        """Restore the initial state."""
        self.state = self._initial_state


class DelayBlock(StatefulBlock):
    """z^-1 unit delay: ``output(t) = state; state(t+1) = input(t)``.

    Acts as the cycle-breaker for algebraic loops: any
    strongly-connected component in the block dependency graph
    must contain at least one DelayBlock for the simulation to be
    well-defined.
    """

    def compute(self, current_iter: int) -> None:
        # Output = current state (which holds the previous input).
        self.set_output_value("OUT", self.state)

    def update_state(self, current_iter: int) -> None:
        # State = current input (becomes the next iteration's output).
        self.state = self.get_input_value("IN")


# ── Concrete primitives (PyCBD library subset) ──────────────────────


class ConstantBlock(Block):
    """Emit a fixed value on the OUT port every iteration."""

    def __init__(self, name: str, value: float = 0.0):
        super().__init__(name, input_names=(), output_names=("OUT",))
        self.value = value

    def compute(self, current_iter: int) -> None:
        self.set_output_value("OUT", self.value)


class GainBlock(Block):
    """Multiply IN by a constant ``k``, write to OUT."""

    def __init__(self, name: str, k: float = 1.0):
        super().__init__(name, input_names=("IN",), output_names=("OUT",))
        self.k = float(k)

    def compute(self, current_iter: int) -> None:
        self.set_output_value("OUT", self.k * self.get_input_value("IN"))


class NegatorBlock(Block):
    """Output the negation of IN."""

    def __init__(self, name: str):
        super().__init__(name, input_names=("IN",), output_names=("OUT",))

    def compute(self, current_iter: int) -> None:
        self.set_output_value("OUT", -self.get_input_value("IN"))


class AdderBlock(Block):
    """Sum an arbitrary number of inputs.

    Inputs are named ``IN1``, ``IN2``, ..., ``INk``.  Useful for
    feedback summing junctions.
    """

    def __init__(self, name: str, num_inputs: int = 2):
        in_names = tuple(f"IN{i+1}" for i in range(num_inputs))
        super().__init__(name, input_names=in_names, output_names=("OUT",))
        self.num_inputs = num_inputs

    def compute(self, current_iter: int) -> None:
        total = sum(self.get_input_value(f"IN{i+1}")
                    for i in range(self.num_inputs))
        self.set_output_value("OUT", total)


class ProductBlock(Block):
    """Multiply an arbitrary number of inputs together."""

    def __init__(self, name: str, num_inputs: int = 2):
        in_names = tuple(f"IN{i+1}" for i in range(num_inputs))
        super().__init__(name, input_names=in_names, output_names=("OUT",))
        self.num_inputs = num_inputs

    def compute(self, current_iter: int) -> None:
        result = 1.0
        for i in range(self.num_inputs):
            result *= self.get_input_value(f"IN{i+1}")
        self.set_output_value("OUT", result)


# ── Compound (hierarchical) block ───────────────────────────────────


class CompoundBlock(Block):
    """A block containing sub-blocks and the connections between them.

    A CompoundBlock is itself a :class:`Block`, so it can nest
    inside another CompoundBlock — that's how PyCBD models
    hierarchy.  External input/output ports on a CompoundBlock are
    declared at construction; internally they're wired to sub-block
    ports via :meth:`add_connection`.
    """

    def __init__(self, name: str,
                 input_names: Iterable[str] = (),
                 output_names: Iterable[str] = ()):
        super().__init__(name, input_names, output_names)
        self.blocks: dict[str, Block] = {}
        self.connections: list[Connection] = []

    def add_block(self, block: Block) -> Block:
        """Add a sub-block.  Returns the block for chaining."""
        if block.name in self.blocks:
            raise ValueError(
                f"CompoundBlock {self.name!r} already has a block "
                f"named {block.name!r}"
            )
        block.parent = self
        self.blocks[block.name] = block
        return block

    def add_connection(self, src_block: str, src_port: str,
                       dst_block: str, dst_port: str) -> Connection:
        """Wire ``src_block.src_port`` to ``dst_block.dst_port``.

        Either side may also be the compound's own external ports
        — pass the compound's name (``self.name``) as ``src_block``
        / ``dst_block`` to refer to ``self``.
        """
        src = self._lookup_port(src_block, src_port, want_output=True)
        dst = self._lookup_port(dst_block, dst_port, want_output=False)
        conn = Connection(src, dst)
        self.connections.append(conn)
        return conn

    def _lookup_port(self, block_name: str, port_name: str,
                     want_output: bool) -> Port:
        if block_name == self.name:
            ports = (self.output_ports if want_output
                     else self.input_ports)
            return ports[port_name]
        block = self.blocks[block_name]
        # On a sub-block, our compound *output* connection comes
        # *from* the sub-block's *output* port — so want_output
        # matches the sub-block port direction.
        ports = (block.output_ports if want_output
                 else block.input_ports)
        return ports[port_name]

    # Flattening for the solver -----------------------------------

    def flatten(self) -> list[Block]:
        """Return a flat list of every leaf block under this compound.

        Recurses into nested CompoundBlocks; the compounds
        themselves are not in the result (they only exist for
        port-routing).
        """
        result: list[Block] = []
        for blk in self.blocks.values():
            if isinstance(blk, CompoundBlock):
                result.extend(blk.flatten())
            else:
                result.append(blk)
        return result

    def get_all_connections(self) -> list[Connection]:
        """Return every connection in this compound and all
        nested compounds (used by the solver to build the dep
        graph)."""
        result = list(self.connections)
        for blk in self.blocks.values():
            if isinstance(blk, CompoundBlock):
                result.extend(blk.get_all_connections())
        return result


# ── GraphView wrapper ───────────────────────────────────────────────


class CBDSimulationView(SimulationView):
    """SimulationView wrapper around a top-level :class:`CompoundBlock`.

    Holds the root compound, the :class:`gvpy.engines.sim.solver
    .CBDSolver` that runs the three-phase Mealy step, and an
    iteration counter.  ``init`` builds the solver's schedule via
    topological sort.

    Like :class:`gvpy.engines.sim.events.EventSimulationView`,
    binding the underlying :class:`gvpy.core.graph.Graph`'s nodes
    to runtime block instances is left to subclasses or the caller
    — the base ``init`` just lets you populate ``self.root``
    directly and then runs the solver over it.
    """

    view_name: str = "sim_cbd"

    def __init__(self, graph: "Graph", delta_t: float = 1.0):
        super().__init__(graph)
        self.clock = DiscreteClock(delta_t=delta_t)
        self.root: Optional[CompoundBlock] = None
        self.solver = None  # CBDSolver, set in init()

    def init(self) -> None:
        """Build the solver schedule from ``self.root``.

        Caller is expected to populate ``self.root`` with a
        :class:`CompoundBlock` before calling :meth:`run` or
        :meth:`step`.  This method validates the root, builds the
        topological schedule, and marks the view initialized.
        """
        # Lazy import to avoid solver <-> cbd circular dep at module
        # import time.
        from .solver import CBDSolver

        if self.root is None:
            raise RuntimeError(
                f"{type(self).__name__}.init: self.root must be set "
                f"to a CompoundBlock before calling init() / run()"
            )
        self.solver = CBDSolver(self.root, clock=self.clock)
        self.solver.init()
        self._initialized = True

    def reset(self) -> None:
        """Reset clock, iteration counter, and stateful block states."""
        self.clock.reset()
        self._now = 0.0
        if self.root is not None:
            for blk in self.root.flatten():
                if isinstance(blk, StatefulBlock):
                    blk.reset()
        self._initialized = False

    def step(self) -> bool:
        """Run one three-phase Mealy step."""
        if self.solver is None:
            return False
        self.solver.step()
        self._now = self.clock.now
        return True

    def get_node_state(self, name: str) -> dict[str, Any]:
        """Return per-block output port snapshot.

        ``name`` matches a block's ``name``; the result is a dict
        of port name -> current value.  Stateful blocks also
        include their internal ``state`` field.
        """
        if self.root is None:
            return {}
        for blk in self.root.flatten():
            if blk.name == name:
                snap = {p: blk.get_output_value(p)
                        for p in blk.output_ports}
                if isinstance(blk, StatefulBlock):
                    snap["__state__"] = blk.state
                return snap
        return {}

    def to_json(self) -> dict[str, Any]:
        d = super().to_json()
        d["paradigm"] = "cbd"
        d["delta_t"] = self.clock.delta_t
        d["iteration"] = self.clock.iteration
        if self.root is not None:
            d["blocks"] = {blk.name: self.get_node_state(blk.name)
                            for blk in self.root.flatten()}
        return d
