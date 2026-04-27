"""Categorize d5_step reorder_enter events by structural shape.

For each engine, group events by (rank, n_entries_bucket).  Bucket
n_entries to: 1, 2, 3, 4-9, 10-39, 40-99, 100+.  Reports a side-by-
side count table so we can see which event categories Py is
missing relative to C.
"""
from __future__ import annotations
import re
import sys
from collections import Counter


_HEADER = re.compile(
    r"\[TRACE d5_step\] reorder_enter "
    r"rank=(\d+) reverse=(\d+) rmx=(\d+) nodes=\[(.+?)\]\s*$"
)


def _bucket(n: int) -> str:
    if n <= 0: return "0"
    if n == 1: return "1"
    if n == 2: return "2"
    if n == 3: return "3"
    if n < 10: return "4-9"
    if n < 40: return "10-39"
    if n < 100: return "40-99"
    return "100+"


def parse(path):
    counts = Counter()  # (rank, bucket, reverse, rmx) -> count
    by_rank = Counter()
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = _HEADER.match(line)
            if not m:
                continue
            rank = int(m.group(1))
            reverse = int(m.group(2))
            rmx = int(m.group(3))
            n_entries = len(m.group(4).split())
            counts[(rank, _bucket(n_entries), reverse, rmx)] += 1
            by_rank[rank] += 1
    return counts, by_rank


def main():
    c_path = sys.argv[1] if len(sys.argv) > 1 else "trace_d5/1879_c_d5.txt"
    p_path = sys.argv[2] if len(sys.argv) > 2 else "trace_d5/1879_py_v45.txt"
    c_counts, c_by_rank = parse(c_path)
    p_counts, p_by_rank = parse(p_path)

    print(f"=== reorder_enter event categories: C vs Py ===")
    print()
    # Per-rank totals
    print(f"  Per-rank event totals")
    print(f"  {'rank':>4}  {'C':>6}  {'Py':>6}  {'Δ(Py-C)':>8}")
    print(f"  {'─'*4}  {'─'*6}  {'─'*6}  {'─'*6}")
    all_ranks = sorted(set(c_by_rank) | set(p_by_rank))
    for r in all_ranks:
        c_n = c_by_rank.get(r, 0)
        p_n = p_by_rank.get(r, 0)
        print(f"  {r:>4}  {c_n:>6}  {p_n:>6}  {p_n-c_n:>+6}")
    print(f"  {'─'*4}  {'─'*6}  {'─'*6}  {'─'*6}")
    print(f"  {'TOTAL':>4}  {sum(c_by_rank.values()):>6}  "
          f"{sum(p_by_rank.values()):>6}  "
          f"{sum(p_by_rank.values())-sum(c_by_rank.values()):>+6}")
    print()
    # Per-(rank, bucket, reverse, rmx) detail
    print(f"  Per-(rank, n_entries_bucket, reverse, rmx) detail")
    print(f"  {'rank':>4}  {'bucket':>7}  {'rev':>3}  "
          f"{'rmx':>3}  {'C':>5}  {'Py':>5}  {'Δ':>5}")
    print(f"  {'─'*4}  {'─'*7}  {'─'*3}  {'─'*3}  {'─'*5}  {'─'*5}  {'─'*5}")
    keys = sorted(set(c_counts) | set(p_counts))
    for k in keys:
        rank, bucket, rev, rmx = k
        c_n = c_counts.get(k, 0)
        p_n = p_counts.get(k, 0)
        marker = "  ←GAP" if c_n != p_n else ""
        print(f"  {rank:>4}  {bucket:>7}  {rev:>3}  {rmx:>3}  "
              f"{c_n:>5}  {p_n:>5}  {p_n-c_n:>+5}{marker}")


if __name__ == "__main__":
    main()
