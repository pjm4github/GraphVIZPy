"""Pass-grouped C-vs-Py comparison for 1879.dot mincross trace.

Top-level (≥4 entries) reorder_enter events are partitioned into
passes by detecting direction reversals in the rank sequence.  For
each pass, we extract the rank → nodes mapping (1 entry per rank)
and compare side-by-side with the corresponding Py pass.

Output:
  Per-pass per-rank match table.  Each cell shows ✓ (full match) or
  ✗ + first divergent idx.  Cumulative all-match percentage at the
  bottom of each pass.

Usage:
    python _pass_compare.py [c_trace] [py_trace] [--max-passes N]
"""
from __future__ import annotations
import argparse
import re


_HEADER = re.compile(
    r"\[TRACE d5_step\] reorder_enter "
    r"rank=(\d+) reverse=(\d+) rmx=(\d+) nodes=\[(.+?)\]\s*$"
)
_NODE = re.compile(r"([^:]+):(-?\d+)(?::(-?\d+(?:\.\d+)?))?")


def _norm(name: str) -> str:
    if name.startswith("_skel_"):
        rest = name[len("_skel_"):]
        u = rest.rfind("_")
        if u > 0 and rest[u + 1:].isdigit():
            return rest[:u]
        return rest
    if name.startswith("_v_") or name.startswith("_icv_"):
        return "v"
    return name


def parse_top_level(path):
    """Return list of (rank, reverse, rmx, [(name, idx, mval)...]).
    Filters out 3-or-fewer-entry events (cluster expand-mincross
    sub-rank events that don't appear at the top level)."""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = _HEADER.match(line)
            if not m:
                continue
            rank = int(m.group(1))
            entries = []
            for part in m.group(4).split():
                tk = _NODE.match(part)
                if tk:
                    entries.append(
                        (_norm(tk.group(1)),
                         int(tk.group(2)),
                         tk.group(3)))
            if len(entries) < 4:
                continue
            out.append(
                (rank, int(m.group(2)), int(m.group(3)), entries))
    return out


def group_by_pass(events):
    """Detect pass boundaries from direction reversals.  A new pass
    starts when the rank sequence reverses direction or when ``rmx``
    changes.  Returns list of passes, each pass is dict {rank:
    entries}.

    The first event always starts pass 0.  In a down pass, ranks
    increase; in an up pass, they decrease.  When the sequence
    breaks the trend, a new pass starts.
    """
    passes = []
    cur = {}
    direction = 0  # 0 = unknown, +1 = down, -1 = up
    prev_rank = None
    prev_rmx = None
    for rank, rev, rmx, entries in events:
        new_pass = False
        if prev_rmx is not None and rmx != prev_rmx:
            new_pass = True
        elif prev_rank is None:
            pass
        elif direction == +1 and rank <= prev_rank:
            new_pass = True
        elif direction == -1 and rank >= prev_rank:
            new_pass = True
        elif direction == 0:
            direction = +1 if rank > prev_rank else -1
        if new_pass:
            passes.append(cur)
            cur = {}
            direction = 0
        if rank not in cur:
            cur[rank] = entries
        prev_rank = rank
        prev_rmx = rmx
        if direction == 0 and len(cur) >= 2:
            # detect direction once we have two ranks in this pass
            ks = list(cur.keys())
            direction = +1 if ks[-1] > ks[-2] else -1
    if cur:
        passes.append(cur)
    return passes


def compare(c_passes, p_passes, max_passes=None):
    n_show = min(len(c_passes), len(p_passes))
    if max_passes:
        n_show = min(n_show, max_passes)
    print(f"=== Pass-by-pass C vs Py rank-state match ===")
    print(f"  C has {len(c_passes)} passes; Py has {len(p_passes)} passes; "
          f"showing {n_show}.")
    print()
    print(f"  {'pass':>4}  {'rank':>4}  {'C-n':>4}  {'Py-n':>4}  "
          f"{'name=':>6}  {'name+mv=':>8}  {'1st-diff':>8}")
    print(f"  {'─'*4}  {'─'*4}  {'─'*4}  {'─'*4}  "
          f"{'─'*6}  {'─'*8}  {'─'*8}")
    total_match = 0
    total_n = 0
    for i in range(n_show):
        c_p = c_passes[i]
        p_p = p_passes[i]
        ranks = sorted(set(c_p.keys()) | set(p_p.keys()))
        pass_match = 0
        pass_n = 0
        for r in ranks:
            c_e = c_p.get(r, [])
            p_e = p_p.get(r, [])
            n = min(len(c_e), len(p_e))
            name_match = sum(1 for j in range(n) if c_e[j][0] == p_e[j][0])
            all_match = sum(
                1 for j in range(n)
                if c_e[j][0] == p_e[j][0] and c_e[j][2] == p_e[j][2])
            first_diff = -1
            for j in range(n):
                if (c_e[j][0] != p_e[j][0] or c_e[j][2] != p_e[j][2]):
                    first_diff = j
                    break
            mark = "" if first_diff < 0 else " ←"
            if i == 0 or first_diff >= 0:  # only print first pass + diverging rows
                print(f"  {i:>4}  {r:>4}  {len(c_e):>4}  {len(p_e):>4}  "
                      f"{name_match:>6}  {all_match:>8}  "
                      f"{first_diff:>8}{mark}")
            pass_match += all_match
            pass_n += max(len(c_e), len(p_e))
        total_match += pass_match
        total_n += pass_n
        pct = (pass_match * 100.0 / pass_n) if pass_n else 0.0
        print(f"  pass {i}: {pass_match}/{pass_n} = {pct:.1f}%")
        print()
    overall_pct = (total_match * 100.0 / total_n) if total_n else 0.0
    print(f"  OVERALL: {total_match}/{total_n} = {overall_pct:.1f}% all-match")


def show_pass_rank(c_passes, p_passes, pass_idx, rank):
    """Side-by-side full dump of one (pass, rank) state."""
    if pass_idx >= len(c_passes) or pass_idx >= len(p_passes):
        return
    c_e = c_passes[pass_idx].get(rank, [])
    p_e = p_passes[pass_idx].get(rank, [])
    print()
    print(f"=== pass {pass_idx} rank {rank} side-by-side ===")
    print(f"  {'idx':>3}  {'C name':<30} {'C mv':>10}  "
          f"{'Py name':<30} {'Py mv':>10}  match")
    n = max(len(c_e), len(p_e))
    for i in range(n):
        cn = c_e[i][0] if i < len(c_e) else "—"
        cv = c_e[i][2] if i < len(c_e) else "—"
        pn = p_e[i][0] if i < len(p_e) else "—"
        pv = p_e[i][2] if i < len(p_e) else "—"
        same = (cn == pn and cv == pv)
        mark = "✓" if same else "✗"
        print(f"  {i:>3}  {cn:<30} {str(cv):>10}  "
              f"{pn:<30} {str(pv):>10}  {mark}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("c_path", nargs="?", default="trace_d5/1879_c_d5.txt")
    ap.add_argument("py_path", nargs="?", default="trace_d5/1879_py_v45.txt")
    ap.add_argument("--max-passes", type=int, default=None)
    ap.add_argument("--show-pass", type=int, default=None,
                    help="Dump full (pass, rank) state for the given pass.")
    ap.add_argument("--show-rank", type=int, default=None)
    args = ap.parse_args()
    c_events = parse_top_level(args.c_path)
    p_events = parse_top_level(args.py_path)
    c_passes = group_by_pass(c_events)
    p_passes = group_by_pass(p_events)
    compare(c_passes, p_passes, args.max_passes)
    if args.show_pass is not None and args.show_rank is not None:
        show_pass_rank(c_passes, p_passes, args.show_pass, args.show_rank)


if __name__ == "__main__":
    main()
