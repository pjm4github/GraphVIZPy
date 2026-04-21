#!/usr/bin/env python3
"""Phase-by-phase divergence diff between C dot.exe and Python GraphvizPy.

Runs both engines on the same dot file with ``GV_TRACE=<channel>``, filters
the ``[TRACE <channel>] ...`` lines from each stderr, normalises numeric
values to a single decimal place, sorts the resulting lines alphabetically,
and prints a unified diff of the two line sets.  Exit 0 on exact match,
exit 1 on any drift.

Usage
-----

    python filters/diff_phases.py <dotfile> <channel> [--tolerance N]
                                [--full-diff] [--show-only-in-c]
                                [--show-only-in-py]

    python filters/diff_phases.py test_data/1444.dot rank
    python filters/diff_phases.py test_data/2734.dot position --tolerance 0.5
    python filters/diff_phases.py test_data/1453.dot spline_path --full-diff

Channels
--------

The ``<channel>`` argument is passed verbatim as ``GV_TRACE=<channel>`` to
both engines.  Comma lists are supported exactly as with the environment
variable; the filters then extracts only lines matching the *first* channel
(so ``rank,order`` runs both phases but diffs ``rank`` only — for order
diffs, run a second time with ``order,rank``).

Normalisation
-------------

- Integers and floats in the message body are rewritten to ``%.Nf`` where
  N defaults to 1 (override with ``--tolerance`` to widen the bin).
- Numbers preceded by a letter or digit (e.g. the ``1`` in ``x1``) are
  left alone, so identifier suffixes don't get mangled.
- Lines are sorted alphabetically after normalisation; this cancels out
  differences in emission order between the two engines when the
  semantic content is the same.

Scope
-----

This tool is deliberately simple: it works best on phases where both
engines emit line-for-line identical message *shapes*.  As of
2026-04-14 that means ``rank`` (node rank assignment) and parts of
``position`` (``set_ycoords``, ``final_pos``).  The ``spline`` and
``order`` channels still diverge in message shape on either side;
they become useful targets as each function lands its literal port.

See ``TODO_dot_splines_port.md`` for the current roster of which
channels are worth diffing.
"""
from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
C_DOT = Path(
    r"C:\Users\pmora\OneDrive\Documents\Git\GitHub\graphviz"
    r"\cmake-build-debug-mingw\cmd\dot\dot.exe"
)
PY_VENV = REPO / ".venv" / "Scripts" / "python.exe"
PY_DOT = REPO / "dot.py"


# Match numbers NOT preceded by an identifier character, so ``x1``
# doesn't get its ``1`` rewritten.  Capture the sign plus integer
# plus optional fractional part.
_NUM_RE = re.compile(r"(?<![A-Za-z0-9_])(-?\d+(?:\.\d+)?)")


def _normalise_numbers(line: str, precision: int) -> str:
    """Round every free-standing number in ``line`` to ``precision`` decimals."""
    fmt = f"%.{precision}f"

    def _repl(m: re.Match[str]) -> str:
        try:
            return fmt % float(m.group(1))
        except ValueError:
            return m.group(1)

    return _NUM_RE.sub(_repl, line)


def _run_engine(
    cmd: list[str],
    dotfile: Path,
    channel: str,
) -> tuple[int, str]:
    """Invoke ``cmd + [-Tsvg, dotfile, -o, devnull]`` with ``GV_TRACE=<channel>``.

    Returns ``(returncode, stderr)``.  stdout is discarded (SVG output).
    """
    env = os.environ.copy()
    env["GV_TRACE"] = channel
    try:
        proc = subprocess.run(
            cmd + ["-Tsvg", str(dotfile), "-o", os.devnull],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return (-1, f"TIMEOUT running {cmd[0]}")
    return (proc.returncode, proc.stderr)


def _filter_channel(stderr: str, channel: str, precision: int) -> list[str]:
    """Extract and normalise trace lines for the given channel.

    For a comma-list channel, filters on the *first* channel only.
    """
    primary = channel.split(",")[0].strip()
    prefix = f"[TRACE {primary}]"
    out = []
    for raw in stderr.splitlines():
        if raw.startswith(prefix):
            out.append(_normalise_numbers(raw, precision))
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="C vs Python trace divergence diff for one phase channel.",
    )
    ap.add_argument("dotfile", type=Path, help="Input .dot file.")
    ap.add_argument(
        "channel",
        help="Trace channel (e.g. rank, position, spline_path). "
        "Passed verbatim as GV_TRACE to both engines; diff filters on the first entry.",
    )
    ap.add_argument(
        "--tolerance",
        type=int,
        default=1,
        metavar="N",
        help="Decimal places for float rounding (default 1). "
        "Lower = stricter, higher = more forgiving.",
    )
    ap.add_argument(
        "--full-diff",
        action="store_true",
        help="Print the full unified diff (default: truncate at 200 lines).",
    )
    ap.add_argument(
        "--show-only-in-c",
        action="store_true",
        help="After the diff, list lines present only in C output.",
    )
    ap.add_argument(
        "--show-only-in-py",
        action="store_true",
        help="After the diff, list lines present only in Python output.",
    )
    args = ap.parse_args()

    if not args.dotfile.exists():
        print(f"error: dotfile not found: {args.dotfile}", file=sys.stderr)
        return 2
    if not C_DOT.exists():
        print(f"error: C dot.exe not found at {C_DOT}", file=sys.stderr)
        return 2
    if not PY_VENV.exists():
        print(f"error: Python venv not found at {PY_VENV}", file=sys.stderr)
        return 2

    print(f"dotfile: {args.dotfile}")
    print(f"channel: {args.channel}")
    print(f"tolerance: {args.tolerance} decimal{'s' if args.tolerance != 1 else ''}")
    print()

    c_rc, c_err = _run_engine([str(C_DOT)], args.dotfile, args.channel)
    if c_rc != 0:
        print(f"warning: C dot.exe exit code {c_rc}", file=sys.stderr)
    py_rc, py_err = _run_engine(
        [str(PY_VENV), str(PY_DOT)], args.dotfile, args.channel
    )
    if py_rc != 0:
        print(f"warning: Python dot.py exit code {py_rc}", file=sys.stderr)

    c_lines = _filter_channel(c_err, args.channel, args.tolerance)
    py_lines = _filter_channel(py_err, args.channel, args.tolerance)

    print(f"C lines:      {len(c_lines)}")
    print(f"Python lines: {len(py_lines)}")

    if c_lines == py_lines:
        print()
        print(f"MATCH: both engines emit identical {args.channel} traces "
              f"({len(c_lines)} lines after normalisation).")
        return 0

    # Compute set-level diff for counts.
    c_set = set(c_lines)
    py_set = set(py_lines)
    only_c = sorted(c_set - py_set)
    only_py = sorted(py_set - c_set)
    common = sorted(c_set & py_set)

    print()
    print(
        f"DRIFT: {len(only_c)} lines only in C, "
        f"{len(only_py)} lines only in Python, "
        f"{len(common)} lines common."
    )
    print()

    diff = list(
        difflib.unified_diff(
            c_lines,
            py_lines,
            fromfile=f"C/{args.channel}",
            tofile=f"py/{args.channel}",
            lineterm="",
            n=3,
        )
    )

    limit = None if args.full_diff else 200
    shown = diff[:limit] if limit else diff
    for line in shown:
        print(line)
    if limit and len(diff) > limit:
        print(f"... (truncated at {limit} of {len(diff)} diff lines; "
              f"pass --full-diff to see everything)")

    if args.show_only_in_c:
        print()
        print(f"--- lines only in C ({len(only_c)}) ---")
        for line in only_c:
            print(line)
    if args.show_only_in_py:
        print()
        print(f"--- lines only in Python ({len(only_py)}) ---")
        for line in only_py:
            print(line)

    return 1


if __name__ == "__main__":
    sys.exit(main())
