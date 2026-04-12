"""Smoke tests for the gvpy.engines.sim package skeleton.

Two end-to-end scenarios:

1. **EventSimulationView / SimPy-style** — a producer process that
   emits a timeout, a consumer process that waits on the producer,
   and we verify the timeline of recorded events.

2. **CBDSimulationView / PyCBD-style** — a feedback ramp built from
   ConstantBlock + AdderBlock + DelayBlock that produces an
   integer ramp 0, 1, 2, 3, ...  Verifies the three-phase Mealy
   semantics and the topological sort + delay-as-cycle-breaker.

Both scenarios also exercise the :class:`SimulationTrace` recorder
and the JSON round-trip.
"""
from __future__ import annotations

from gvpy.core.graph import Graph
from gvpy.engines.sim import (
    AdderBlock,
    CBDSimulationView,
    CBDSolver,
    CompoundBlock,
    ConstantBlock,
    DelayBlock,
    Environment,
    EventSimulationView,
    GainBlock,
    SimulationTrace,
    topological_sort,
)


# ── Event-driven smoke test ─────────────────────────────────────────


def test_event_environment_basic_timeout():
    """Two processes, each yielding a Timeout, fire in time order."""
    env = Environment()
    fired = []

    def proc(name, delay):
        yield env.timeout(delay)
        fired.append((env.now, name))

    env.process(proc("A", 5))
    env.process(proc("B", 2))
    env.process(proc("C", 8))
    env.run(until=20)

    assert fired == [(2.0, "B"), (5.0, "A"), (8.0, "C")]


def test_event_process_waits_on_event():
    """A process can yield on a manually-triggered Event."""
    env = Environment()
    log = []

    signal = env.event()

    def waiter():
        value = yield signal
        log.append(("waiter", env.now, value))

    def trigger():
        yield env.timeout(3)
        signal.succeed("hello")
        log.append(("trigger", env.now))

    env.process(waiter())
    env.process(trigger())
    env.run(until=10)

    assert ("trigger", 3.0) in log
    assert ("waiter", 3.0, "hello") in log


def test_event_simulation_view_basic():
    """EventSimulationView attaches to a Graph and runs an env."""
    g = Graph(name="g", directed=True)
    g.add_node("A")
    g.add_node("B")

    view = EventSimulationView(g)
    g.attach_view(view, name="sim")

    fired = []

    def proc(name):
        yield view.env.timeout(5)
        fired.append(name)

    view.processes["A"] = view.env.process(proc("A"))
    view.processes["B"] = view.env.process(proc("B"))

    view.run(until=10)

    assert sorted(fired) == ["A", "B"]
    assert view.now == 5.0
    assert view.is_done() is True


def test_event_view_to_json_round_trip_basic():
    """to_json captures paradigm, time, and process count."""
    g = Graph(name="g", directed=True)
    view = EventSimulationView(g)
    view.init()
    view.env.timeout(7)  # schedule but don't run
    snap = view.to_json()
    assert snap["paradigm"] == "event"
    assert snap["heap_size"] == 1
    assert snap["now"] == 0.0


# ── CBD smoke test ──────────────────────────────────────────────────


def test_cbd_topological_sort_breaks_delay_cycle():
    """A pure feedback ring is sortable iff a DelayBlock is present."""
    # Constant -> Adder.IN1 ; Adder.OUT -> Delay.IN ; Delay.OUT -> Adder.IN2
    one = ConstantBlock("one", value=1.0)
    add = AdderBlock("add", num_inputs=2)
    delay = DelayBlock("delay", initial_state=0.0)

    cbd = CompoundBlock("ramp")
    cbd.add_block(one)
    cbd.add_block(add)
    cbd.add_block(delay)
    cbd.add_connection("one", "OUT", "add", "IN1")
    cbd.add_connection("delay", "OUT", "add", "IN2")
    cbd.add_connection("add", "OUT", "delay", "IN")

    schedule = topological_sort(cbd.flatten())
    names = [b.name for b in schedule]

    # Delay must come before non-delay blocks that depend on it.
    # Constant has no dependencies; both come before adder.
    assert names.index("delay") < names.index("add")
    assert names.index("one") < names.index("add")


def test_cbd_three_phase_mealy_produces_integer_ramp():
    """Constant + Adder + Delay feedback produces 0, 1, 2, 3, ...

    Block diagram::

                  +-------+
        one ----> | IN1   |
                  | Adder |---+----> Delay --+
            +---->| IN2   |   |              |
            |     +-------+   |              |
            |                 v              |
            +---- (delay state holds last add output)

    Iteration 0: delay.state = 0, output = 0; add reads (1, 0) -> 1
                 update: delay.state := add.out = 1
    Iteration 1: delay.output = 1; add reads (1, 1) -> 2
                 update: delay.state := 2
    Iteration 2: delay.output = 2; add reads (1, 2) -> 3
                 ...
    """
    one = ConstantBlock("one", value=1.0)
    add = AdderBlock("add", num_inputs=2)
    delay = DelayBlock("delay", initial_state=0.0)

    cbd = CompoundBlock("ramp")
    cbd.add_block(one)
    cbd.add_block(add)
    cbd.add_block(delay)
    cbd.add_connection("one", "OUT", "add", "IN1")
    cbd.add_connection("delay", "OUT", "add", "IN2")
    cbd.add_connection("add", "OUT", "delay", "IN")

    solver = CBDSolver(cbd)
    solver.init()

    samples = []
    for _ in range(5):
        solver.step()
        samples.append(add.get_output_value("OUT"))

    assert samples == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_cbd_simulation_view_basic():
    """CBDSimulationView wraps a CompoundBlock and runs via run()."""
    g = Graph(name="g", directed=True)
    g.add_node("source")
    g.add_node("scale")

    view = CBDSimulationView(g, delta_t=1.0)
    g.attach_view(view, name="cbd")

    one = ConstantBlock("source", value=2.0)
    gain = GainBlock("scale", k=3.0)

    root = CompoundBlock("top")
    root.add_block(one)
    root.add_block(gain)
    root.add_connection("source", "OUT", "scale", "IN")

    view.root = root
    view.run(max_steps=4)

    state = view.get_node_state("scale")
    assert state["OUT"] == 6.0  # 2 * 3
    assert view.now == 4.0


def test_cbd_view_to_json_includes_block_state():
    """to_json snapshots delta_t, iteration, and per-block outputs."""
    g = Graph(name="g", directed=True)
    g.add_node("k")

    view = CBDSimulationView(g, delta_t=0.5)
    one = ConstantBlock("k", value=42.0)
    root = CompoundBlock("top")
    root.add_block(one)
    view.root = root
    view.run(max_steps=3)

    snap = view.to_json()
    assert snap["paradigm"] == "cbd"
    assert snap["delta_t"] == 0.5
    assert snap["iteration"] == 3
    assert snap["blocks"]["k"]["OUT"] == 42.0


# ── SimulationTrace smoke test ──────────────────────────────────────


def test_simulation_trace_records_and_round_trips():
    trace = SimulationTrace()
    for i in range(4):
        trace.record(float(i), "x", i * 2)
    assert trace.get_series("x") == [(0.0, 0), (1.0, 2), (2.0, 4), (3.0, 6)]
    assert trace.names() == ["x"]

    snap = trace.to_json()
    fresh = SimulationTrace()
    fresh.from_json(snap)
    assert fresh.get_series("x") == trace.get_series("x")
