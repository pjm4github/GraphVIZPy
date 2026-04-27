"""Side-by-side comparison table for C vs Py mincross traces.

Reads ``[TRACE d5_step] reorder_enter`` events from two trace files
and emits:

  1. Per-rank summary: total entries, name matches, all-matches
     (name + mval), first divergence index.
  2. Side-by-side detail of any rank with mismatches (idx, C name,
     C mval, Py name, Py mval, match marker).
  3. Per-pass match progression (each paired event compared).

Usage:
    python _compare_table.py [c_trace] [py_trace]

Defaults: trace_d5/1879_c_d5.txt and trace_d5/1879_py_v44b.txt.
"""
from __future__ import annotations
import re
import sys


_NODE = re.compile(r"([^:]+):(-?\d+)(?::(-?\d+(?:\.\d+)?))?")


def _norm(name: str) -> str:
    """Match Py skeleton names to C cluster names."""
    if name.startswith("_skel_"):
        rest = name[len("_skel_"):]
        u = rest.rfind("_")
        if u > 0 and rest[u + 1:].isdigit():
            return rest[:u]
        return rest
    if name.startswith("_v_") or name.startswith("_icv_"):
        return "v"
    return name


def parse_events(path):
    """Return list of (line_num, rank, reverse, rmx, [(name, idx, mval), ...])."""
    out = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            m = re.match(
                r"\[TRACE d5_step\] reorder_enter "
                r"rank=(\d+) reverse=(\d+) rmx=(\d+) nodes=\[(.+?)\]\s*$",
                line)
            if not m:
                continue
            entries = []
            for part in m.group(4).split():
                tk = _NODE.match(part)
                if tk:
                    entries.append(
                        (_norm(tk.group(1)),
                         int(tk.group(2)),
                         tk.group(3)))
            out.append((ln, int(m.group(1)), int(m.group(2)),
                        int(m.group(3)), entries))
    return out


def first_reorder_per_rank(events):
    """Return {rank: (line, reverse, rmx, entries)} for the FIRST
    event observed per rank."""
    out = {}
    seen = set()
    for ln, r, rev, rmx, entries in events:
        if r in seen:
            continue
        seen.add(r)
        out[r] = (ln, rev, rmx, entries)
    return out


def per_rank_summary(c_first, p_first, label_c="C", label_p="Py"):
    """Print the per-rank match table."""
    ranks = sorted(set(c_first.keys()) | set(p_first.keys()))
    print(f"=== Per-rank first-reorder_enter match: {label_c} vs {label_p} ===")
    print(f"  {'rank':>4}  {'Cn':>3}  {'Pyn':>3}  "
          f"{'name=':>5}  {'name+mv=':>8}  {'1st-diff':>8}  detail")
    print(f"  {'─'*4}  {'─'*3}  {'─'*3}  {'─'*5}  {'─'*8}  {'─'*8}")
    total_match = 0
    total_n = 0
    diverged_ranks = []
    for r in ranks:
        c = c_first.get(r, (0, 0, 0, []))[3]
        p = p_first.get(r, (0, 0, 0, []))[3]
        n = min(len(c), len(p))
        name_match = sum(1 for i in range(n) if c[i][0] == p[i][0])
        all_match = sum(
            1 for i in range(n)
            if c[i][0] == p[i][0] and c[i][2] == p[i][2])
        first_diff = -1
        diff_detail = ""
        for i in range(n):
            if (c[i][0] != p[i][0] or c[i][2] != p[i][2]):
                first_diff = i
                diff_detail = (
                    f"C={c[i][0]}@mv{c[i][2]} "
                    f"Py={p[i][0]}@mv{p[i][2]}")
                break
        total_match += all_match
        total_n += max(len(c), len(p))
        marker = "" if first_diff < 0 else "←"
        print(f"  {r:>4}  {len(c):>3}  {len(p):>3}  "
              f"{name_match:>5}  {all_match:>8}  "
              f"{first_diff:>8}{marker}  {diff_detail}")
        if first_diff >= 0:
            diverged_ranks.append(r)
    pct = (total_match * 100.0 / total_n) if total_n else 0.0
    print(f"  {'─'*48}")
    print(f"  TOTAL: {total_match}/{total_n} = {pct:.1f}% all-match")
    return diverged_ranks


def side_by_side_detail(c_first, p_first, ranks, label_c="C", label_p="Py"):
    """For each rank with divergences, print the side-by-side table."""
    if not ranks:
        return
    print()
    print(f"=== Side-by-side detail (diverged ranks only) ===")
    for r in ranks:
        c = c_first.get(r, (0, 0, 0, []))[3]
        p = p_first.get(r, (0, 0, 0, []))[3]
        print()
        print(f"  ┌── rank {r} ──")
        print(f"  │ {'idx':>3}  "
              f"{label_c+' name':<28} {label_c+' mv':>10}  "
              f"{label_p+' name':<28} {label_p+' mv':>10}  match")
        n = max(len(c), len(p))
        for i in range(n):
            cn = c[i][0] if i < len(c) else "—"
            cv = c[i][2] if i < len(c) else "—"
            pn = p[i][0] if i < len(p) else "—"
            pv = p[i][2] if i < len(p) else "—"
            same = (cn == pn and cv == pv)
            mark = "✓" if same else "✗"
            print(f"  │ {i:>3}  {cn:<28} {str(cv):>10}  "
                  f"{pn:<28} {str(pv):>10}  {mark}")


def pass_progression(c_events, p_events, max_passes=10):
    """Compare paired events sequentially up to max_passes per direction.

    Identifies the FIRST paired event where C and Py disagree; prior
    events are reported as matching.  Useful to see how far into the
    mincross loop the engines stay aligned.
    """
    print()
    print(f"=== Pass-by-pass match (paired events) ===")
    print(f"  {'C events':>10}  {'Py events':>10}  {'paired':>8}  matched")
    paired = min(len(c_events), len(p_events))
    matched = 0
    first_div = -1
    for i in range(paired):
        c_ln, c_r, c_rev, c_rmx, c_e = c_events[i]
        p_ln, p_r, p_rev, p_rmx, p_e = p_events[i]
        if (c_r != p_r or c_rev != p_rev or c_rmx != p_rmx
                or len(c_e) != len(p_e)):
            first_div = i
            break
        ok = True
        for j in range(len(c_e)):
            if c_e[j] != p_e[j]:
                ok = False
                break
        if not ok:
            first_div = i
            break
        matched += 1
    print(f"  {len(c_events):>10}  {len(p_events):>10}  "
          f"{paired:>8}  {matched}")
    if first_div >= 0 and first_div < paired:
        c_ln, c_r, c_rev, c_rmx, c_e = c_events[first_div]
        p_ln, p_r, p_rev, p_rmx, p_e = p_events[first_div]
        print(f"  → first divergence at paired event #{first_div}: "
              f"C line {c_ln} (rank={c_r} reverse={c_rev}) "
              f"vs Py line {p_ln} (rank={p_r} reverse={p_rev})")


def main():
    c_path = sys.argv[1] if len(sys.argv) > 1 else "trace_d5/1879_c_d5.txt"
    p_path = sys.argv[2] if len(sys.argv) > 2 else "trace_d5/1879_py_v44b.txt"
    c_events = parse_events(c_path)
    p_events = parse_events(p_path)
    c_first = first_reorder_per_rank(c_events)
    p_first = first_reorder_per_rank(p_events)
    diverged = per_rank_summary(c_first, p_first)
    side_by_side_detail(c_first, p_first, diverged)
    pass_progression(c_events, p_events)


if __name__ == "__main__":
    main()
