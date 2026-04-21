"""Compare expand_cluster orderings between C and Python traces."""
import re
import sys

def get_expand(path, cluster_name):
    lines = {}
    capturing = False
    with open(path) as f:
        for line in f:
            if f"expand_cluster {cluster_name}:" in line:
                capturing = True
                continue
            elif capturing:
                m = re.match(r"\[TRACE order\]\s+rank (\d+): (.*)", line.strip())
                if m:
                    lines[int(m.group(1))] = m.group(2)
                else:
                    break
    return lines

c_trace = sys.argv[1] if len(sys.argv) > 1 else "trace_reference.txt"
p_trace = sys.argv[2] if len(sys.argv) > 2 else "trace_python.txt"

for cl in ["cluster_6754", "cluster_4252"]:
    c = get_expand(c_trace, cl)
    p = get_expand(p_trace, cl)
    matches = sum(1 for r in c if c.get(r) == p.get(r))
    print(f"{cl}: {matches}/{len(c)} expand ranks match")
    for r in sorted(c.keys()):
        if c.get(r) != p.get(r):
            print(f"  rank {r}: C= {c[r]}")
            pv = p.get(r, "N/A")
            print(f"           Py={pv}")
