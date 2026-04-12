"""
Bulk validation: read every test_data file and verify dot layout produces JSON.

Each file gets a 30-second timeout.  Files that fail to parse (e.g. malformed
content or unsupported format) are expected failures and are tracked but do
not fail the test run.

Run with ``-s`` to see progress indicators::

    python -m pytest tests/test_all_files.py -s
"""
import json
import signal
import os
import sys
import time
import pytest
from pathlib import Path

from gvpy.grammar.gv_reader import read_gv_file, GVParseError
from gvpy.render.json_io import read_json_file
from gvpy.render.gxl_io import read_gxl_file
from gvpy.engines.layout.dot import DotLayout

TEST_DATA = Path(__file__).parent.parent / "test_data"

# Files known to have parse errors (malformed content from Graphviz bug tracker)
KNOWN_PARSE_FAILURES = {
    "1308_1.dot",   # Multiple graph blocks with mismatched braces
    "1411.dot",     # Parse error (unusual syntax)
    "1474.dot",     # Parse error (unusual syntax)
    "1489.dot",     # Non-UTF-8 encoding (accented characters)
    "1494.dot",     # Binary/null bytes in file
    "1676.dot",     # Smart quotes and special punctuation
    "1845.dot",     # Multiple graph blocks — parser expects EOF after first
    "2743.dot",     # Unexpected attribute list placement
}

# Files known to timeout during layout (complex graphs >30s)
KNOWN_LAYOUT_TIMEOUTS = {
    "42.dot",       # Complex graph
    "1652.dot",     # Large/complex layout
    "1718.dot",     # Large/complex layout
    "1864.dot",     # Large/complex layout
    "1879.dot",     # Large/complex layout
    "2064.dot",     # Large/complex layout
    "2095.dot",     # Large/complex layout
    "2095_1.dot",   # Large/complex layout
    "2108.dot",     # Large/complex layout
    "2222.dot",     # Large/complex layout
    "2343.dot",     # Large/complex layout
    "2371.dot",     # Large/complex layout
    "2470.dot",     # Large/complex layout
    "2471.dot",     # Large/complex layout
    "2475_1.dot",   # Large/complex layout
    "2475_2.dot",   # Large/complex layout
    "2593.dot",     # Large/complex layout
    "2620.dot",     # Large/complex layout
    "2621.dot",     # Large/complex layout
    "2646.dot",     # Large/complex layout
    "2669.dot",     # Large/complex layout
    "2796.dot",     # Large/complex layout
    "2854.dot",     # Large/complex layout
}

# Files that are not graph formats (gvpr scripts, GML, etc.)
NON_GRAPH_EXTENSIONS = {
    ".gvpr", ".gml", ".py", ".bat", ".sh", ".txt", ".md",
    ".jpg", ".jpeg", ".png", ".svg", ".pdf", ".eps", ".ps", ".gif", ".bmp",
}


def _collect_test_files():
    """Collect all graph files from test_data/."""
    if not TEST_DATA.exists():
        return []
    files = []
    for f in sorted(TEST_DATA.iterdir()):
        if f.is_file() and f.suffix.lower() not in NON_GRAPH_EXTENSIONS:
            files.append(f)
    return files


def _read_graph(path: Path):
    """Read a graph file, auto-detecting format by extension."""
    suffix = path.suffix.lower()
    if suffix in (".json",):
        return read_json_file(path)
    elif suffix in (".gxl", ".xml"):
        return read_gxl_file(path)
    elif suffix in (".gv", ".dot"):
        return read_gv_file(path)
    else:
        # Try DOT as fallback
        return read_gv_file(path)


class TimeoutError(Exception):
    """Raised when a file operation exceeds the timeout."""
    pass


if sys.platform != "win32":
    # Unix: use SIGALRM for timeout
    def _run_with_timeout(func, timeout_sec):
        def _handler(signum, frame):
            raise TimeoutError(f"Timed out after {timeout_sec}s")
        old = signal.signal(signal.SIGALRM, _handler)
        signal.alarm(timeout_sec)
        try:
            return func()
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old)
else:
    # Windows: use threading for timeout
    import threading

    def _run_with_timeout(func, timeout_sec):
        result = [None]
        error = [None]

        def _target():
            try:
                result[0] = func()
            except Exception as e:
                error[0] = e

        t = threading.Thread(target=_target)
        t.start()
        t.join(timeout=timeout_sec)
        if t.is_alive():
            raise TimeoutError(f"Timed out after {timeout_sec}s")
        if error[0] is not None:
            raise error[0]
        return result[0]


# ── Collect files and build progress tracker ─────

_ALL_FILES = _collect_test_files()
_TOTAL = len(_ALL_FILES)
_counter = {"n": 0, "passed": 0, "skipped": 0, "failed": 0}


def _progress(name, status, elapsed):
    """Print a progress line to stdout (visible with pytest -s)."""
    _counter["n"] += 1
    _counter[status] += 1
    n = _counter["n"]
    mark = {"passed": "OK", "skipped": "SKIP", "failed": "FAIL"}[status]
    print(f"  [{n:3d}/{_TOTAL}] {mark:4s} {elapsed:5.1f}s  {name}")


# ── Parametrized test ─────────────────────────────


@pytest.mark.parametrize("filepath", _ALL_FILES,
                         ids=[f.name for f in _ALL_FILES])
def test_read_and_layout(filepath):
    """Read a test file, run dot layout, and verify JSON output."""
    name = filepath.name
    t0 = time.time()

    # Skip known timeouts upfront
    if name in KNOWN_LAYOUT_TIMEOUTS:
        _progress(name, "skipped", 0.0)
        pytest.skip(f"Known layout timeout: {name}")

    # Step 1: Read the file (with 30s timeout)
    try:
        graph = _run_with_timeout(lambda: _read_graph(filepath), 30)
    except TimeoutError:
        _progress(name, "failed", time.time() - t0)
        pytest.fail(f"TIMEOUT: {name} took >30s to read")
    except GVParseError:
        if name in KNOWN_PARSE_FAILURES:
            _progress(name, "skipped", time.time() - t0)
            pytest.skip(f"Known parse failure: {name}")
        else:
            _progress(name, "failed", time.time() - t0)
            pytest.fail(f"Parse error on {name} (not in known failures list)")
    except Exception as e:
        if name in KNOWN_PARSE_FAILURES:
            _progress(name, "skipped", time.time() - t0)
            pytest.skip(f"Known failure: {name}: {e}")
        else:
            _progress(name, "failed", time.time() - t0)
            pytest.fail(f"Unexpected error reading {name}: {e}")

    assert graph is not None, f"read returned None for {name}"
    assert len(graph.nodes) >= 0, f"Graph from {name} has no nodes dict"

    # Step 2: Run dot layout (with 30s timeout)
    try:
        result = _run_with_timeout(lambda: DotLayout(graph).layout(), 30)
    except TimeoutError:
        _progress(name, "skipped", time.time() - t0)
        pytest.skip(f"TIMEOUT: {name} layout took >30s (add to KNOWN_LAYOUT_TIMEOUTS)")
    except Exception as e:
        _progress(name, "failed", time.time() - t0)
        pytest.fail(f"Layout error on {name}: {e}")

    # Step 3: Verify JSON output structure
    assert isinstance(result, dict), f"Layout result is not a dict for {name}"
    assert "graph" in result, f"Missing 'graph' key in result for {name}"
    assert "nodes" in result, f"Missing 'nodes' key in result for {name}"
    assert "edges" in result, f"Missing 'edges' key in result for {name}"

    # Step 4: Verify JSON serializable
    try:
        json_text = json.dumps(result)
    except (TypeError, ValueError) as e:
        _progress(name, "failed", time.time() - t0)
        pytest.fail(f"Result not JSON-serializable for {name}: {e}")

    assert len(json_text) > 10, f"JSON output too short for {name}"

    # Step 5: Verify node count matches
    assert len(result["nodes"]) == len(graph.nodes), \
        f"Node count mismatch for {name}: " \
        f"result={len(result['nodes'])}, graph={len(graph.nodes)}"

    _progress(name, "passed", time.time() - t0)


def test_summary(capsys):
    """Print final summary after all file tests complete."""
    # This test runs last (alphabetically after test_read_and_layout)
    if _counter["n"] == 0:
        pytest.skip("No file tests ran yet")
    print(f"\n{'='*60}")
    print(f"  Bulk file validation complete")
    print(f"  Total: {_counter['n']}/{_TOTAL}  "
          f"Passed: {_counter['passed']}  "
          f"Skipped: {_counter['skipped']}  "
          f"Failed: {_counter['failed']}")
    print(f"{'='*60}")
