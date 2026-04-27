"""Compare first reorder_enter per rank between C and Py v44 traces.

Reports per-rank: total entries, name match count, all-match count
(name + index + mval), and the first divergence index per rank.
"""
import re
import sys


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


def first_reorder_enter_by_rank(path):
    """Return {rank: [(name, idx, mval), ...]} for the FIRST
    reorder_enter event observed for each rank."""
    out = {}
    seen = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(
                r"\[TRACE d5_step\] reorder_enter "
                r"rank=(\d+) reverse=(\d+) rmx=(\d+) nodes=\[(.+?)\]\s*$",
                line)
            if not m:
                continue
            rank = int(m.group(1))
            if rank in seen:
                continue
            seen.add(rank)
            entries = []
            for part in m.group(4).split():
                tk = _NODE.match(part)
                if tk:
                    name = _norm(tk.group(1))
                    idx = int(tk.group(2))
                    mv = tk.group(3)
                    entries.append((name, idx, mv))
            out[rank] = entries
    return out


def main():
    c_path = sys.argv[1] if len(sys.argv) > 1 else "trace_d5/1879_c_d5.txt"
    p_path = sys.argv[2] if len(sys.argv) > 2 else "trace_d5/1879_py_v44.txt"
    c = first_reorder_enter_by_rank(c_path)
    p = first_reorder_enter_by_rank(p_path)
    ranks = sorted(set(c.keys()) | set(p.keys()))
    total_match = 0
    total_n = 0
    print(f"=== Per-rank match (C vs Py first reorder_enter) ===")
    print(f"  rank  C_n  Py_n  name_match  all_match  first_diff_idx  detail")
    for r in ranks:
        c_e = c.get(r, [])
        p_e = p.get(r, [])
        n = min(len(c_e), len(p_e))
        name_match = sum(
            1 for i in range(n) if c_e[i][0] == p_e[i][0])
        all_match = sum(
            1 for i in range(n)
            if c_e[i][0] == p_e[i][0] and c_e[i][2] == p_e[i][2])
        first_diff = -1
        diff_detail = ""
        for i in range(n):
            if (c_e[i][0] != p_e[i][0]
                    or c_e[i][2] != p_e[i][2]):
                first_diff = i
                diff_detail = (
                    f"C={c_e[i][0]}@mv{c_e[i][2]} "
                    f"Py={p_e[i][0]}@mv{p_e[i][2]}")
                break
        total_match += all_match
        total_n += max(len(c_e), len(p_e))
        print(f"  {r:>4}  {len(c_e):>3}  {len(p_e):>4}  "
              f"{name_match:>10}  {all_match:>9}  {first_diff:>14}  "
              f"{diff_detail}")
    pct = (total_match * 100.0 / total_n) if total_n else 0.0
    print(f"  TOTAL: {total_match}/{total_n} = {pct:.1f}% all-match")


if __name__ == "__main__":
    main()
