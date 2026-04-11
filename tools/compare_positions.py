"""Compare C reference ns_solved X positions with Python final_pos X positions.

For rankdir=LR, the NS-solved X in C corresponds to the cross-rank direction,
which maps to the final X coordinate in both C and Python output.
"""
import re
import sys

def parse_c_ns_solved(path):
    """Extract ns_solved x_pos from C trace."""
    positions = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'\[TRACE position\] ns_solved: (\S+) x_pos=(\d+)', line)
            if m:
                positions[m.group(1)] = int(m.group(2))
    return positions

def parse_py_final_pos(path):
    """Extract final_pos x from Python trace."""
    positions = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'\[TRACE position\] final_pos: (\S+) x=([-\d.]+)', line)
            if m:
                positions[m.group(1)] = float(m.group(2))
    return positions

def parse_c_final_pos(path):
    """Extract final_pos from C trace (for node sizes)."""
    sizes = {}
    with open(path) as f:
        for line in f:
            m = re.match(r'\[TRACE position\] final_pos: (\S+) x=\S+ y=\S+ w=([\d.]+) h=([\d.]+)', line)
            if m:
                sizes[m.group(1)] = (float(m.group(2)), float(m.group(3)))
    return sizes

def main():
    c_trace = sys.argv[1] if len(sys.argv) > 1 else 'trace_reference.txt'
    py_trace = sys.argv[2] if len(sys.argv) > 2 else 'trace_python.txt'

    c_pos = parse_c_ns_solved(c_trace)
    py_pos = parse_py_final_pos(py_trace)
    c_sizes = parse_c_final_pos(c_trace)

    all_nodes = sorted(set(c_pos.keys()) | set(py_pos.keys()))

    print(f"{'Node':<12} {'C x_pos':>8} {'Py x':>8} {'Delta':>8} {'C w':>6} {'Py w':>6}")
    print("-" * 58)

    deltas = []
    for node in all_nodes:
        c_x = c_pos.get(node)
        py_x = py_pos.get(node)
        c_w, c_h = c_sizes.get(node, (0, 0))
        # Python w from trace
        py_w = 0
        if c_x is not None and py_x is not None:
            delta = py_x - c_x
            deltas.append((abs(delta), node, c_x, py_x, delta))
            print(f"{node:<12} {c_x:>8} {py_x:>8.1f} {delta:>+8.1f} {c_w:>6.1f}")
        elif c_x is not None:
            print(f"{node:<12} {c_x:>8} {'N/A':>8} {'':>8} {c_w:>6.1f}")
        else:
            print(f"{node:<12} {'N/A':>8} {py_x:>8.1f}")

    if deltas:
        deltas.sort(reverse=True)
        print(f"\n--- Top 20 largest absolute deltas ---")
        print(f"{'Node':<12} {'C x_pos':>8} {'Py x':>8} {'Delta':>8}")
        for abs_d, node, c_x, py_x, delta in deltas[:20]:
            print(f"{node:<12} {c_x:>8} {py_x:>8.1f} {delta:>+8.1f}")

        abs_deltas = [d[0] for d in deltas]
        print(f"\nMean abs delta: {sum(abs_deltas)/len(abs_deltas):.1f}")
        print(f"Max abs delta:  {max(abs_deltas):.1f}")
        print(f"Nodes compared: {len(deltas)}")

        # Check if there's a constant offset
        raw_deltas = [d[4] for d in deltas]
        mean_delta = sum(raw_deltas) / len(raw_deltas)
        print(f"Mean delta (signed): {mean_delta:.1f}")

if __name__ == '__main__':
    main()
