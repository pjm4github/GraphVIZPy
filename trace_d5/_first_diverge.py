"""Find the first reorder_enter event where Py diverges from C.

Pairs up reorder_enter events sequentially (i.e. the Nth event in C
is matched against the Nth event in Py).  Reports the first pair
that disagrees in any way (rank, reverse, names, indices, mvals).
"""
from __future__ import annotations
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


def parse_events(path):
    out = []
    with open(path, encoding="utf-8") as f:
        for ln, line in enumerate(f, 1):
            m = re.match(
                r"\[TRACE d5_step\] reorder_enter "
                r"rank=(\d+) reverse=(\d+) rmx=(\d+) nodes=\[(.+?)\]\s*$",
                line)
            if not m:
                continue
            rank = int(m.group(1))
            reverse = int(m.group(2))
            rmx = int(m.group(3))
            entries = []
            for part in m.group(4).split():
                tk = _NODE.match(part)
                if tk:
                    entries.append(
                        (_norm(tk.group(1)),
                         int(tk.group(2)),
                         tk.group(3)))
            out.append((ln, rank, reverse, rmx, entries))
    return out


def main():
    c_path = sys.argv[1] if len(sys.argv) > 1 else "trace_d5/1879_c_d5.txt"
    p_path = sys.argv[2] if len(sys.argv) > 2 else "trace_d5/1879_py_v44b.txt"
    c = parse_events(c_path)
    p = parse_events(p_path)
    print(f"C has {len(c)} reorder_enter events; Py has {len(p)}.")
    print()
    for i, (ce, pe) in enumerate(zip(c, p)):
        c_ln, c_r, c_rev, c_rmx, c_entries = ce
        p_ln, p_r, p_rev, p_rmx, p_entries = pe
        if c_r != p_r or c_rev != p_rev or c_rmx != p_rmx:
            print(f"Event #{i}: header mismatch")
            print(f"  C  line {c_ln}: rank={c_r} reverse={c_rev} rmx={c_rmx}")
            print(f"  Py line {p_ln}: rank={p_r} reverse={p_rev} rmx={p_rmx}")
            return
        # Compare entries
        if len(c_entries) != len(p_entries):
            print(f"Event #{i}: entry count mismatch "
                  f"({len(c_entries)} vs {len(p_entries)}) at rank {c_r}")
            return
        for j, (ce_, pe_) in enumerate(zip(c_entries, p_entries)):
            if ce_ != pe_:
                print(f"Event #{i} (rank={c_r} reverse={c_rev}, "
                      f"line C={c_ln} Py={p_ln}): first diff at idx {j}")
                print(f"  C  : {ce_}")
                print(f"  Py : {pe_}")
                # Show a window of context
                print()
                print(f"  Context (idx {max(0, j-2)}..{min(len(c_entries), j+5)}):")
                for k in range(max(0, j-2), min(len(c_entries), j+5)):
                    print(f"    {k:>3}  C={c_entries[k]!s:<50}  "
                          f"Py={p_entries[k]!s:<50}")
                return
    print(f"All {min(len(c), len(p))} paired events match.")


if __name__ == "__main__":
    main()
